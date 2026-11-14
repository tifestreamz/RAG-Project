"""Multi-format policy document ingestion, chunking, and FAISS + SQLite index builder."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Literal

from bs4 import BeautifulSoup
import faiss
from pypdf import PdfReader

from app_config import Settings, get_settings
from rag.embeddings import EmbeddingBackend

_MD_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_NUM_HEADING_RE = re.compile(
    r"^(?:Section\s+\d+\.?\s+.+|(?:\d+(?:\.\d+)?)\s+[A-Z][^\n]{3,90})$"
)
_DOC_ID_RE = re.compile(r"Document ID:\s*(POL-\d+)", re.IGNORECASE)
_TITLE_RE = re.compile(r"Policy Title:\s*(.+)", re.IGNORECASE)
_CAT_RE = re.compile(r"Category:\s*`?([a-zA-Z0-9_-]+)`?", re.IGNORECASE)


@dataclass(slots=True)
class PolicySection:
    """Intermediate parsed section before word-window chunking."""

    section_path: str
    page_or_anchor: str
    text: str


@dataclass(slots=True)
class PolicyChunk:
    """Indexed policy chunk persisted in SQLite and aligned by `chunk_idx` with FAISS."""

    chunk_idx: int
    chunk_id: str
    doc_id: str
    doc_title: str
    source_file: str
    file_format: str
    category: str
    section_path: str
    page_or_anchor: str
    word_count: int
    text: str


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "section"


def _extract_metadata(raw_head: str, fallback_name: str) -> tuple[str, str, str]:
    clean = re.sub(r"<[^>]+>", " ", raw_head).replace("**", "")
    m_id = _DOC_ID_RE.search(clean)
    m_title = _TITLE_RE.search(clean)
    m_cat = _CAT_RE.search(clean)
    doc_id = m_id.group(1).upper() if m_id else fallback_name.upper()
    doc_title = (
        m_title.group(1).strip()
        if m_title
        else fallback_name.replace("_", " ").title()
    )
    category = m_cat.group(1).strip().lower() if m_cat else "general"
    return doc_id, doc_title, category


def _parse_markdown(path: Path) -> tuple[dict[str, str], list[PolicySection]]:
    raw = path.read_text(encoding="utf-8")
    doc_id, doc_title, category = _extract_metadata(raw[:1200], path.stem)
    sections: list[PolicySection] = []
    h_stack: dict[int, str] = {}
    current_lines: list[str] = []
    current_path = "Document Overview"
    current_anchor = "#overview"

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(
                PolicySection(
                    section_path=current_path,
                    page_or_anchor=current_anchor,
                    text=body,
                )
            )
        current_lines.clear()

    for line in raw.splitlines():
        m = _MD_HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            heading = m.group(2).strip()
            h_stack[level] = heading
            for deeper in [k for k in list(h_stack) if k > level]:
                del h_stack[deeper]
            parts = [h_stack[k] for k in sorted(h_stack) if k >= 2]
            current_path = " > ".join(parts) if parts else heading
            current_anchor = f"#{_slugify(heading)}"
            current_lines.append(heading)
        else:
            current_lines.append(line)
    flush()
    meta = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "category": category,
        "source_file": path.name,
        "file_format": "markdown",
    }
    return meta, sections


def _table_to_lines(table_tag: Any) -> list[str]:
    rows: list[str] = []
    headers: list[str] = []
    for tr in table_tag.find_all("tr"):
        ths = [th.get_text(" ", strip=True) for th in tr.find_all("th")]
        if ths and not headers:
            headers = ths
            continue
        tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if not tds:
            continue
        if headers and len(headers) == len(tds):
            rows.append(" | ".join(f"{h}: {v}" for h, v in zip(headers, tds)))
        else:
            rows.append(" | ".join(tds))
    return rows


def _parse_html(path: Path) -> tuple[dict[str, str], list[PolicySection]]:
    raw = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    article = soup.find("article")
    raw_head = article.get_text("\n", strip=True)[:1200] if article else soup.get_text("\n", strip=True)[:1200]
    doc_id, doc_title, category = _extract_metadata(raw_head, path.stem)
    if article and article.get("data-doc-id"):
        doc_id = str(article["data-doc-id"]).upper()
    if article and article.get("data-category"):
        category = str(article["data-category"]).lower()

    sections: list[PolicySection] = []
    h2_text = ""
    h3_text = ""
    current_lines: list[str] = []
    current_path = "Document Overview"
    current_anchor = "#overview"

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(
                PolicySection(
                    section_path=current_path,
                    page_or_anchor=current_anchor,
                    text=body,
                )
            )
        current_lines.clear()

    root = article or soup.body or soup
    for elem in root.find_all(["h1", "h2", "h3", "p", "ul", "ol", "table"], recursive=True):
        if elem.find_parent(["table"]) and elem.name != "table":
            continue
        if elem.find_parent(["ul", "ol"]) and elem.name != elem.find_parent(["ul", "ol"]).name:
            continue
        name = elem.name
        if name in {"h1", "h2", "h3"}:
            flush()
            heading = elem.get_text(" ", strip=True)
            if name == "h1":
                h2_text, h3_text = "", ""
                current_path = heading
            elif name == "h2":
                h2_text, h3_text = heading, ""
                current_path = heading
            else:
                h3_text = heading
                current_path = f"{h2_text} > {h3_text}" if h2_text else h3_text
            elem_id = elem.get("id")
            current_anchor = f"#{elem_id or _slugify(heading)}"
            current_lines.append(heading)
        elif name == "table":
            current_lines.extend(_table_to_lines(elem))
        elif name in {"ul", "ol"}:
            for li in elem.find_all("li", recursive=False):
                txt = li.get_text(" ", strip=True)
                if txt:
                    current_lines.append(f"- {txt}")
        else:
            txt = elem.get_text(" ", strip=True)
            if txt:
                current_lines.append(txt)
    flush()
    meta = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "category": category,
        "source_file": path.name,
        "file_format": "html",
    }
    return meta, sections


def _parse_line_oriented_sections(
    lines: list[str], page_label: str | None = None
) -> list[PolicySection]:
    sections: list[PolicySection] = []
    current_heading = f"Page {page_label}" if page_label else "Document Overview"
    current_lines: list[str] = []

    def flush(idx: int) -> None:
        body = "\n".join(current_lines).strip()
        if body:
            anchor = (
                f"p. {page_label}"
                if page_label
                else f"#{_slugify(current_heading)}-{idx}"
            )
            sections.append(
                PolicySection(
                    section_path=current_heading,
                    page_or_anchor=anchor,
                    text=body,
                )
            )
        current_lines.clear()

    sec_idx = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if _NUM_HEADING_RE.match(line):
            flush(sec_idx)
            sec_idx += 1
            current_heading = line
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush(sec_idx)
    return sections


def _parse_pdf(path: Path) -> tuple[dict[str, str], list[PolicySection]]:
    reader = PdfReader(str(path))
    first_page = reader.pages[0].extract_text() or "" if reader.pages else ""
    doc_id, doc_title, category = _extract_metadata(first_page[:1400], path.stem)
    sections: list[PolicySection] = []
    for idx, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        page_sections = _parse_line_oriented_sections(txt.splitlines(), page_label=str(idx))
        sections.extend(page_sections)
    meta = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "category": category,
        "source_file": path.name,
        "file_format": "pdf",
    }
    return meta, sections


def _parse_txt(path: Path) -> tuple[dict[str, str], list[PolicySection]]:
    raw = path.read_text(encoding="utf-8")
    doc_id, doc_title, category = _extract_metadata(raw[:1200], path.stem)
    sections = _parse_line_oriented_sections(raw.splitlines(), page_label=None)
    meta = {
        "doc_id": doc_id,
        "doc_title": doc_title,
        "category": category,
        "source_file": path.name,
        "file_format": "txt",
    }
    return meta, sections


def parse_policy_file(path: Path) -> tuple[dict[str, str], list[PolicySection]]:
    """Parse `.md`, `.html`, `.pdf`, or `.txt` policy file into metadata and sections."""
    suffix = path.suffix.lower()
    if suffix == ".md":
        return _parse_markdown(path)
    if suffix in {".html", ".htm"}:
        return _parse_html(path)
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".txt":
        return _parse_txt(path)
    raise ValueError(f"Unsupported policy file format: {path.suffix}")


def _merge_tiny_sections(sections: list[PolicySection], min_words: int = 32) -> list[PolicySection]:
    """Attach heading-only or very short intro blocks onto the following section."""
    if not sections:
        return []
    merged: list[PolicySection] = []
    pending: PolicySection | None = None
    for sec in sections:
        words = sec.text.split()
        if pending is not None:
            combined_text = f"{pending.text}\n\n{sec.text}".strip()
            sec = PolicySection(
                section_path=sec.section_path or pending.section_path,
                page_or_anchor=sec.page_or_anchor,
                text=combined_text,
            )
            pending = None
            words = sec.text.split()
        if len(words) < min_words:
            pending = sec
        else:
            merged.append(sec)
    if pending is not None:
        if merged:
            prev = merged[-1]
            merged[-1] = PolicySection(
                section_path=prev.section_path,
                page_or_anchor=prev.page_or_anchor,
                text=f"{prev.text}\n\n{pending.text}".strip(),
            )
        else:
            merged.append(pending)
    return merged


def chunk_sections(
    meta: dict[str, str],
    sections: list[PolicySection],
    start_idx: int,
    chunk_size_words: int,
    chunk_overlap_words: int,
) -> list[PolicyChunk]:
    """Split sections into bounded overlapping word chunks with stable IDs."""
    chunks: list[PolicyChunk] = []
    idx = start_idx
    prepared = _merge_tiny_sections(sections)
    step = max(50, chunk_size_words - chunk_overlap_words)

    for sec_num, sec in enumerate(prepared, start=1):
        words = sec.text.split()
        if len(words) <= chunk_size_words:
            windows = [" ".join(words)]
        else:
            windows = []
            for pos in range(0, len(words), step):
                part = words[pos : pos + chunk_size_words]
                windows.append(" ".join(part))
                if pos + chunk_size_words >= len(words):
                    break

        for part_num, window_text in enumerate(windows, start=1):
            chunk_id = f"{meta['doc_id']}-S{sec_num:02d}-C{part_num:02d}"
            chunks.append(
                PolicyChunk(
                    chunk_idx=idx,
                    chunk_id=chunk_id,
                    doc_id=meta["doc_id"],
                    doc_title=meta["doc_title"],
                    source_file=meta["source_file"],
                    file_format=meta["file_format"],
                    category=meta["category"],
                    section_path=sec.section_path,
                    page_or_anchor=sec.page_or_anchor,
                    word_count=len(window_text.split()),
                    text=window_text,
                )
            )
            idx += 1
    return chunks


def compute_corpus_sha256(policies_dir: Path) -> str:
    """Compute a stable SHA-256 fingerprint across all files in `policies_dir`."""
    hasher = hashlib.sha256()
    for path in sorted(p for p in policies_dir.iterdir() if p.is_file()):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _write_sqlite(db_path: Path, chunks: list[PolicyChunk]) -> None:
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_idx INTEGER PRIMARY KEY,
                chunk_id TEXT UNIQUE NOT NULL,
                doc_id TEXT NOT NULL,
                doc_title TEXT NOT NULL,
                source_file TEXT NOT NULL,
                file_format TEXT NOT NULL,
                category TEXT NOT NULL,
                section_path TEXT NOT NULL,
                page_or_anchor TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX idx_chunks_doc_id ON chunks (doc_id)")
        conn.execute("CREATE INDEX idx_chunks_category ON chunks (category)")
        conn.executemany(
            """
            INSERT INTO chunks (
                chunk_idx, chunk_id, doc_id, doc_title, source_file,
                file_format, category, section_path, page_or_anchor,
                word_count, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.chunk_idx,
                    c.chunk_id,
                    c.doc_id,
                    c.doc_title,
                    c.source_file,
                    c.file_format,
                    c.category,
                    c.section_path,
                    c.page_or_anchor,
                    c.word_count,
                    c.text,
                )
                for c in chunks
            ],
        )
        conn.commit()
    finally:
        conn.close()


def build_index(
    settings: Settings | None = None,
    provider_override: Literal["auto", "gemini", "hash"] | None = None,
    force: bool = True,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Ingest `policies/` and build FAISS + SQLite + manifest index in `data/rag_index/`."""
    cfg = settings or get_settings()
    if provider_override == "auto" or provider_override is None:
        provider = cfg.effective_embedding_provider
    else:
        provider = provider_override

    index_dir = cfg.rag_index_dir
    index_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = index_dir / "manifest.json"
    faiss_path = index_dir / "faiss.index"
    db_path = index_dir / "chunks.db"

    corpus_sha = compute_corpus_sha256(cfg.policies_dir)
    if (
        not force
        and manifest_path.exists()
        and faiss_path.exists()
        and db_path.exists()
    ):
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.get("corpus_sha256") == corpus_sha
            and existing.get("embedding_provider") == provider
            and existing.get("embedding_dim") == cfg.embedding_dim
        ):
            return existing

    supported_ext = {".md", ".html", ".htm", ".pdf", ".txt"}
    policy_files = sorted(
        p
        for p in cfg.policies_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported_ext
    )
    if not policy_files:
        raise FileNotFoundError(f"No policy files found in {cfg.policies_dir}")

    all_chunks: list[PolicyChunk] = []
    doc_summaries: list[dict[str, Any]] = []
    for file_path in policy_files:
        meta, sections = parse_policy_file(file_path)
        file_chunks = chunk_sections(
            meta=meta,
            sections=sections,
            start_idx=len(all_chunks),
            chunk_size_words=cfg.chunk_size_words,
            chunk_overlap_words=cfg.chunk_overlap_words,
        )
        all_chunks.extend(file_chunks)
        doc_summaries.append(
            {
                "doc_id": meta["doc_id"],
                "doc_title": meta["doc_title"],
                "source_file": meta["source_file"],
                "file_format": meta["file_format"],
                "category": meta["category"],
                "chunks": len(file_chunks),
            }
        )

    embedder = EmbeddingBackend(
        provider=provider,
        api_key=cfg.gemini_api_key,
        model_name=cfg.gemini_embedding_model,
        dim=cfg.embedding_dim,
    )
    embed_inputs = [
        f"{c.doc_id} | {c.doc_title} | {c.section_path}\n{c.text}"
        for c in all_chunks
    ]
    vectors = embedder.embed_texts(
        embed_inputs,
        task_type="RETRIEVAL_DOCUMENT",
        cancel_event=cancel_event,
    )

    faiss_index = faiss.IndexFlatIP(cfg.embedding_dim)
    faiss_index.add(vectors)
    faiss_tmp = index_dir / "faiss.index.tmp"
    db_tmp = index_dir / "chunks.db.tmp"
    manifest_tmp = index_dir / "manifest.json.tmp"
    faiss.write_index(faiss_index, str(faiss_tmp))
    _write_sqlite(db_tmp, all_chunks)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "corpus_sha256": corpus_sha,
        "embedding_provider": provider,
        "embedding_model": (
            cfg.gemini_embedding_model if provider == "gemini" else "signed-ngram-hash"
        ),
        "embedding_dim": cfg.embedding_dim,
        "doc_count": len(doc_summaries),
        "chunk_count": len(all_chunks),
        "chunk_size_words": cfg.chunk_size_words,
        "chunk_overlap_words": cfg.chunk_overlap_words,
        "documents": doc_summaries,
    }
    manifest_tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(faiss_tmp, faiss_path)
    os.replace(db_tmp, db_path)
    os.replace(manifest_tmp, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Northstar HR Policy RAG index.")
    parser.add_argument(
        "--provider",
        choices=["auto", "gemini", "hash"],
        default="auto",
        help="Embedding provider override (default: auto).",
    )
    parser.add_argument(
        "--skip-if-unchanged",
        action="store_true",
        help="Skip rebuild when corpus hash and provider match existing manifest.",
    )
    args = parser.parse_args()
    manifest = build_index(
        provider_override=args.provider,
        force=not args.skip_if_unchanged,
    )
    print(
        json.dumps(
            {k: v for k, v in manifest.items() if k != "documents"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
