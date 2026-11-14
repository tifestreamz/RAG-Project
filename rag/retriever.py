"""Hybrid Dense (FAISS) + Sparse (BM25) + Reciprocal Rank Fusion retriever."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Literal

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from app_config import Settings, get_settings
from rag.embeddings import EmbeddingBackend
from rag.ingest import PolicyChunk, build_index

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")
_DOC_REF_RE = re.compile(r"\b(POL-\d{3})\b", re.IGNORECASE)

_STOPWORDS = frozenset(
    {
        "a", "about", "an", "and", "are", "as", "ask", "at", "be", "best", "by",
        "can", "could", "do", "does", "explain", "for", "from", "get", "give",
        "good", "help", "how", "i", "if", "in", "is", "it", "know", "make",
        "may", "me", "might", "my", "need", "of", "on", "or", "our", "please",
        "should", "show", "tell", "thank", "thanks", "that", "the", "this",
        "to", "use", "want", "what", "when", "where", "which", "who", "will",
        "with", "would", "you", "your",
    }
)

HR_SYNONYMS: dict[str, str] = {
    "pto": "paid time off vacation leave days accrual carryover",
    "vacation": "paid time off pto leave blackout advance notice",
    "workcation": "temporary international remote work foreign country rolling 30 days",
    "abroad": "international remote work foreign jurisdiction country",
    "international": "temporary international remote work cross-border travel loaner",
    "wfh": "remote hybrid telework work from home",
    "remote": "hybrid telework domestic relocation international work",
    "prod-admin": "production admin privileged access customer pii loaner laptop",
    "vpn": "infosec zero trust vpn mfa remote access security",
    "loaner": "clean travel loaner laptop infosec wipe",
    "401k": "retirement plan employer match vesting",
    "benefits": "health medical dental vision 401k wellness learning stipend",
    "wellness": "monthly wellness reimbursement stipend gym therapy",
    "l&d": "learning development conference tuition book stipend",
    "probation": "90 day probationary onboarding standing",
    "fmla": "parental medical bereavement family leave",
    "parental": "maternity paternity bonding parental leave",
    "bereavement": "funeral bereavement immediate family leave",
    "reimburse": "expense travel per diem lodging airfare receipt",
    "expense": "reimbursement travel meal lodging airfare receipt",
    "laptop": "equipment hardware macbook upgrade loaner",
    "contractor": "1099 independent contractor vendor intern",
    "intern": "fixed term intern stipend contractor",
    "harassment": "conduct discrimination retaliation ethics p1 confidential",
    "retaliation": "ethics conduct harassment escalation p1",
    "ticket": "hr case triage escalation sla p1 p2 p3",
    "holiday": "company holiday floating holiday winter recharge shutdown",
    "blackout": "payroll close year end blackout window",
}


def tokenize(text: str) -> list[str]:
    """Tokenize lowercase alphanumeric terms, filtering trivial stopwords."""
    return [
        t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1
    ]


def expand_hr_query(query: str) -> str:
    """Append domain synonym terms for better recall across policy jargon."""
    lower = query.lower()
    expansions: list[str] = []
    for key, extra in HR_SYNONYMS.items():
        if key in lower:
            expansions.append(extra)
    if not expansions:
        return query
    return f"{query} {' '.join(expansions)}"


@dataclass(slots=True)
class RetrievalHit:
    """Single retrieved policy chunk with fused and component scores."""

    chunk_id: str
    doc_id: str
    doc_title: str
    source_file: str
    file_format: str
    category: str
    section_path: str
    page_or_anchor: str
    rrf_score: float
    dense_score: float
    bm25_score: float
    snippet: str
    text: str

    def citation_label(self) -> str:
        """Human-readable citation label used in responses and traces."""
        return f"[{self.doc_id} | {self.section_path} ({self.page_or_anchor})]"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResponse:
    """Structured output from `HybridPolicyRetriever.search`."""

    query: str
    expanded_query: str
    mode: str
    below_threshold: bool
    hits: list[RetrievalHit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "expanded_query": self.expanded_query,
            "mode": self.mode,
            "below_threshold": self.below_threshold,
            "hits": [h.to_dict() for h in self.hits],
        }


def _make_snippet(
    text: str, query_tokens: list[str], max_chars: int = 480
) -> str:
    """Extract highest-relevance sentences centered on non-generic query matches."""
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean

    skip_generic = {"northstar", "company", "policy", "policies", "employee", "employees"}
    focus_tokens = [t for t in query_tokens if t not in skip_generic] or query_tokens

    sentences = re.split(r"(?<=[.!?])\s+|\s+\|\s+", clean)
    scored: list[tuple[int, int, str]] = []
    for idx, sent in enumerate(sentences):
        s_lower = sent.lower()
        hits = sum(1 for tok in set(focus_tokens) if tok in s_lower)
        scored.append((hits, -idx, sent))
    scored.sort(reverse=True)

    chosen: list[tuple[int, str]] = []
    total_len = 0
    for hits, neg_idx, sent in scored:
        if hits == 0 and chosen:
            continue
        add_len = len(sent) + (3 if chosen else 0)
        if chosen and total_len + add_len > max_chars:
            continue
        chosen.append((-neg_idx, sent))
        total_len += add_len
        if total_len >= max_chars:
            break

    if not chosen:
        return clean[:max_chars].strip() + "..."
    chosen.sort(key=lambda pair: pair[0])
    joined = " ".join(s for _, s in chosen).strip()
    if len(joined) > max_chars:
        return joined[: max_chars - 3].rstrip() + "..."
    return joined


class HybridPolicyRetriever:
    """FAISS + BM25Okapi + Reciprocal Rank Fusion retriever over Northstar policies."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        index_dir = self.settings.rag_index_dir
        manifest_path = index_dir / "manifest.json"
        faiss_path = index_dir / "faiss.index"
        db_path = index_dir / "chunks.db"

        if not (manifest_path.exists() and faiss_path.exists() and db_path.exists()):
            build_index(self.settings, force=True)

        self.manifest: dict[str, Any] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        self.faiss_index = faiss.read_index(str(faiss_path))
        self.chunks = self._load_chunks(db_path)

        provider = self.manifest.get("embedding_provider", "hash")
        if provider == "gemini" and not self.settings.has_valid_gemini_key:
            # Rebuild locally with hash backend if prebuilt index used Gemini without runtime key
            build_index(self.settings, provider_override="hash", force=True)
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.faiss_index = faiss.read_index(str(faiss_path))
            self.chunks = self._load_chunks(db_path)
            provider = "hash"

        emb_model = (
            str(self.manifest.get("embedding_model") or self.settings.gemini_embedding_model)
            if provider == "gemini"
            else self.settings.gemini_embedding_model
        )
        self.embedder = EmbeddingBackend(
            provider=provider,
            api_key=self.settings.gemini_api_key,
            model_name=emb_model,
            dim=int(self.manifest.get("embedding_dim", self.settings.embedding_dim)),
        )

        tokenized_corpus = [
            tokenize(
                f"{c.doc_id} {c.doc_title} {c.section_path} {c.category} {c.text}"
            )
            for c in self.chunks
        ]
        self.bm25 = BM25Okapi(tokenized_corpus)

    @staticmethod
    def _load_chunks(db_path: Path) -> list[PolicyChunk]:
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                """
                SELECT chunk_idx, chunk_id, doc_id, doc_title, source_file,
                       file_format, category, section_path, page_or_anchor,
                       word_count, text
                FROM chunks
                ORDER BY chunk_idx ASC
                """
            ).fetchall()
        finally:
            conn.close()
        return [PolicyChunk(*row) for row in rows]

    def search(
        self,
        query: str,
        top_k: int | None = None,
        category: str | None = None,
        doc_id: str | None = None,
        mode: Literal["hybrid", "dense_only", "bm25_only"] = "hybrid",
        rrf_k: int = 60,
    ) -> RetrievalResponse:
        """Retrieve ranked policy chunks using Hybrid RRF, Dense-only, or BM25-only."""
        k = top_k or self.settings.rag_top_k
        expanded = expand_hr_query(query)
        raw_tokens = tokenize(query)
        expanded_tokens = tokenize(expanded)
        explicit_doc_refs = {m.upper() for m in _DOC_REF_RE.findall(query)}

        # Dense similarity scores aligned to chunk_idx
        q_vec = self.embedder.embed_texts([expanded], task_type="RETRIEVAL_QUERY")
        scores_arr, idx_arr = self.faiss_index.search(q_vec, len(self.chunks))
        dense_by_idx: dict[int, float] = {}
        for idx, sc in zip(idx_arr[0].tolist(), scores_arr[0].tolist()):
            if idx >= 0:
                dense_by_idx[idx] = float(sc)

        # BM25 scores aligned to chunk_idx
        bm25_scores = self.bm25.get_scores(expanded_tokens or raw_tokens)

        # Apply optional metadata filtering
        cat_norm = category.strip().lower() if category else None
        doc_norm = doc_id.strip().upper() if doc_id else None
        candidate_indices = [
            c.chunk_idx
            for c in self.chunks
            if (cat_norm is None or c.category.lower() == cat_norm)
            and (doc_norm is None or c.doc_id.upper() == doc_norm)
        ]

        if not candidate_indices:
            return RetrievalResponse(
                query=query,
                expanded_query=expanded,
                mode=mode,
                below_threshold=True,
                hits=[],
            )

        # Build ranks only for meaningful positive evidence
        dense_ranked = sorted(
            [i for i in candidate_indices if dense_by_idx.get(i, 0.0) > 0.0],
            key=lambda i: dense_by_idx.get(i, 0.0),
            reverse=True,
        )
        bm25_ranked = sorted(
            [i for i in candidate_indices if float(bm25_scores[i]) > 0.0],
            key=lambda i: float(bm25_scores[i]),
            reverse=True,
        )
        dense_rank_map = {idx: rank for rank, idx in enumerate(dense_ranked, start=1)}
        bm25_rank_map = {idx: rank for rank, idx in enumerate(bm25_ranked, start=1)}

        scored: list[tuple[float, int]] = []
        for idx in candidate_indices:
            chunk = self.chunks[idx]
            d_score = dense_by_idx.get(idx, 0.0)
            b_score = float(bm25_scores[idx])
            exact_boost = 0.015 if chunk.doc_id.upper() in explicit_doc_refs else 0.0

            if mode == "dense_only":
                final_score = d_score + exact_boost
            elif mode == "bm25_only":
                final_score = b_score + exact_boost
            else:
                d_rrf = (
                    1.0 / (rrf_k + dense_rank_map[idx]) if idx in dense_rank_map else 0.0
                )
                b_rrf = (
                    1.0 / (rrf_k + bm25_rank_map[idx]) if idx in bm25_rank_map else 0.0
                )
                final_score = d_rrf + b_rrf + exact_boost
            scored.append((final_score, idx))

        scored.sort(key=lambda item: item[0], reverse=True)
        top_items = scored[:k]

        hits: list[RetrievalHit] = []
        for score, idx in top_items:
            chunk = self.chunks[idx]
            d_score = dense_by_idx.get(idx, 0.0)
            b_score = float(bm25_scores[idx])
            if mode == "hybrid" and score <= 0.0:
                continue
            if mode == "bm25_only" and b_score <= 0.0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    doc_title=chunk.doc_title,
                    source_file=chunk.source_file,
                    file_format=chunk.file_format,
                    category=chunk.category,
                    section_path=chunk.section_path,
                    page_or_anchor=chunk.page_or_anchor,
                    rrf_score=round(score, 6),
                    dense_score=round(d_score, 4),
                    bm25_score=round(b_score, 4),
                    snippet=_make_snippet(chunk.text, raw_tokens or expanded_tokens),
                    text=chunk.text,
                )
            )

        below_threshold = self._is_below_threshold(hits, mode=mode)
        return RetrievalResponse(
            query=query,
            expanded_query=expanded,
            mode=mode,
            below_threshold=below_threshold,
            hits=hits,
        )

    def _is_below_threshold(self, hits: list[RetrievalHit], mode: str) -> bool:
        if not hits:
            return True
        top = hits[0]
        min_dense = 0.58 if self.embedder.provider == "gemini" else 0.22
        if mode == "dense_only":
            return top.dense_score < min_dense
        if mode == "bm25_only":
            return top.bm25_score < 4.5
        if top.rrf_score < self.settings.rag_min_rrf_score:
            return True
        if top.bm25_score < 4.5 and top.dense_score < min_dense:
            return True
        return False

    def get_section(self, doc_id: str, section_query: str = "") -> list[PolicyChunk]:
        """Retrieve ordered chunks for a specific document ID and optional section filter."""
        norm_id = doc_id.strip().upper()
        norm_sec = section_query.strip().lower()
        doc_chunks = [c for c in self.chunks if c.doc_id.upper() == norm_id]
        if not norm_sec:
            return doc_chunks
        matched = [
            c
            for c in doc_chunks
            if norm_sec in c.section_path.lower() or norm_sec in c.text.lower()
        ]
        return matched or doc_chunks[:2]
