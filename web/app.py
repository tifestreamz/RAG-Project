"""FastAPI application wiring MCPClientManager, AgentOrchestrator, and SPA UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Literal

from bs4 import BeautifulSoup, NavigableString, Tag
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

from agent.compliance import MockHRDataStore
from agent.orchestrator import AgentOrchestrator
from app_config import PROJECT_ROOT, get_settings
from mcp_server.client import MCPClientManager
from rag.ingest import build_index, parse_policy_file

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class ChatRequest(BaseModel):
    """User chat request payload."""

    message: str = Field(..., max_length=4000)
    provider_override: Literal["auto", "gemini", "mock"] | None = None
    context: dict[str, Any] | None = None


class ConfirmTicketRequest(BaseModel):
    """Explicit confirmation payload required to persist a synthetic HR ticket."""

    proposed_ticket: dict[str, Any]
    confirmed: bool = True


DEMO_TASKS: list[dict[str, Any]] = [
    {
        "id": "demo-1",
        "title": "Demo Task 1: International Workcation & Policy Conflict (Maya Lin)",
        "badge": "POL-003 + POL-005 + Mock HR + P2 Escalation",
        "prompt": (
            "Can Maya Lin (EMP-1042) take a 6-week remote workcation from Lisbon, Portugal? "
            "Check her rolling 12-month allowance and security tier, evaluate compliance, "
            "draft an approval/escalation email, and prepare a mock HR ticket."
        ),
    },
    {
        "id": "demo-2",
        "title": "Demo Task 2: Year-End PTO, Winter Recharge & Mock Ticket (Carlos Vega)",
        "badge": "POL-001 + POL-002 + Balance + Confirm Gate",
        "prompt": (
            "Carlos Vega (EMP-1018) wants to take 5 PTO days starting Dec 21 through year-end. "
            "Check his PTO balance, explain how Winter Recharge applies, and prepare a mock HR ticket."
        ),
    },
    {
        "id": "demo-3",
        "title": "Bonus: Prod-Admin International Travel Loaner (Liam O'Connor)",
        "badge": "POL-003 + POL-005 + P2 InfoSec",
        "prompt": (
            "Liam O'Connor (EMP-1055) requests 10 calendar days working remotely from Madrid, Spain "
            "with 20 business days notice. Check compliance, InfoSec laptop rules, and draft escalation."
        ),
    },
    {
        "id": "demo-4",
        "title": "Bonus: Confidential P1 Ethics & Anti-Retaliation Triage",
        "badge": "POL-010 + POL-011 + P1 Confidential",
        "prompt": (
            "An employee reports manager retaliation and harassment after raising an expense concern. "
            "How should People Ops triage and route this case under Northstar policy?"
        ),
    },
    {
        "id": "demo-5",
        "title": "Bonus: Contractor Ineligibility Check (Jordan Brooks)",
        "badge": "POL-012 + POL-004 + POL-006",
        "prompt": (
            "Can contractor Jordan Brooks (EMP-1089) claim a $500 home office ergonomic chair stipend "
            "and take 3 paid PTO days?"
        ),
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize RAG index manifest, connect MCP client session, and tear down cleanly."""
    settings = get_settings()
    manifest_path = settings.rag_index_dir / "manifest.json"
    faiss_path = settings.rag_index_dir / "faiss.index"
    db_path = settings.rag_index_dir / "chunks.db"

    if manifest_path.exists() and faiss_path.exists() and db_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = build_index(settings=settings, provider_override="hash", force=True)

    mcp_client = MCPClientManager(settings=settings)
    try:
        tools = await mcp_client.connect()
    except Exception:
        tools = []
    orchestrator = AgentOrchestrator(mcp_client=mcp_client, settings=settings)

    app.state.settings = settings
    app.state.rag_manifest = manifest
    app.state.mcp_client = mcp_client
    app.state.mcp_tools_initial = [t.name for t in tools]
    app.state.orchestrator = orchestrator

    cancel_event = threading.Event()
    upgrade_task: asyncio.Task[None] | None = None
    if (
        settings.effective_embedding_provider == "gemini"
        and (
            manifest.get("embedding_provider") != "gemini"
            or manifest.get("embedding_model") != settings.gemini_embedding_model
        )
    ):
        async def _upgrade_embeddings() -> None:
            try:
                upgraded = await asyncio.to_thread(
                    build_index,
                    settings,
                    "gemini",
                    True,
                    cancel_event,
                )
                app.state.rag_manifest = upgraded
                logger.info(
                    "Background RAG index upgraded to %s (%d chunks)",
                    upgraded.get("embedding_model"),
                    upgraded.get("chunk_count", 0),
                )
            except InterruptedError:
                pass
            except Exception as exc:
                logger.warning(
                    "Background Gemini embedding upgrade skipped (%s); keeping hash index",
                    exc,
                )

        upgrade_task = asyncio.create_task(_upgrade_embeddings())

    try:
        yield
    finally:
        cancel_event.set()
        if upgrade_task is not None and not upgrade_task.done():
            upgrade_task.cancel()
            try:
                await upgrade_task
            except asyncio.CancelledError:
                pass
        await mcp_client.close()


app = FastAPI(
    title="Northstar Cloud Labs HR Policy & Operations Copilot",
    description="Agentic Hybrid RAG + Model Context Protocol (MCP) HR Compliance Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    """Serve the accessible single-page web application."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/architecture", include_in_schema=False)
async def serve_architecture() -> FileResponse:
    """Serve the live system architecture, CI/CD, and evaluation walkthrough page."""
    return FileResponse(STATIC_DIR / "architecture.html")


@app.get("/corpus", include_in_schema=False)
async def serve_corpus() -> FileResponse:
    """Serve the browsable policy corpus and indexed chunks inspector page."""
    return FileResponse(STATIC_DIR / "corpus.html")


_CATEGORY_LABELS: dict[str, str] = {
    "pto_holidays": "Leave",
    "remote_work": "Workplace",
    "expenses": "Finance",
    "security": "Security",
    "benefits": "Benefits",
    "onboarding": "Workforce",
    "equipment": "IT",
    "leave": "Leave",
    "conduct": "Compliance",
}


def _humanize_category(raw: str) -> str:
    return _CATEGORY_LABELS.get(raw.lower(), raw.replace("_", " ").title())


def _clean_doc_title(doc_id: str, raw_title: str) -> str:
    # Make extracted PDF filenames (e.g. "05 Information Security...") readable
    cleaned = raw_title.strip()
    if len(cleaned) > 3 and cleaned[:2].isdigit() and cleaned[2] == " ":
        cleaned = cleaned[3:]
    return cleaned


def _html_inline_to_md(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""
    tag = node.name.lower()
    if tag == "br":
        return "\n"
    inner = "".join(_html_inline_to_md(child) for child in node.children)
    if tag in {"strong", "b"}:
        core = inner.strip()
        if not core:
            return ""
        lead = " " if inner.startswith(" ") else ""
        trail = " " if inner.endswith(" ") else ""
        return f"{lead}**{core}**{trail}"
    if tag in {"em", "i"}:
        core = inner.strip()
        if not core:
            return ""
        lead = " " if inner.startswith(" ") else ""
        trail = " " if inner.endswith(" ") else ""
        return f"{lead}*{core}*{trail}"
    if tag == "code":
        core = inner.strip()
        return f"`{core}`" if core else ""
    return inner


def _html_table_to_md(table_tag: Tag) -> list[str]:
    rows_raw: list[tuple[bool, list[str]]] = []
    for tr in table_tag.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        is_header = all(c.name.lower() == "th" for c in cells)
        vals = [
            re.sub(r"\s+", " ", _html_inline_to_md(c)).strip().replace("|", "\\|")
            for c in cells
        ]
        rows_raw.append((is_header, vals))

    if not rows_raw:
        return []

    header_idx = next((i for i, (is_h, _) in enumerate(rows_raw) if is_h), 0)
    headers = rows_raw[header_idx][1]
    body_rows = [vals for i, (_, vals) in enumerate(rows_raw) if i != header_idx]
    col_count = max([len(headers)] + [len(r) for r in body_rows])

    def pad(row: list[str]) -> list[str]:
        return row + [""] * (col_count - len(row))

    lines = [
        "| " + " | ".join(pad(headers)) + " |",
        "| " + " | ".join([":---"] * col_count) + " |",
    ]
    for r in body_rows:
        lines.append("| " + " | ".join(pad(r)) + " |")
    return lines


def _extract_readable_html_sections(policy_path: Path) -> list[dict[str, Any]]:
    raw = policy_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    root = soup.find("article") or soup.body or soup

    sections: list[dict[str, Any]] = []
    current_heading = "Overview"
    current_anchor = "#overview"
    blocks: list[str] = []

    def flush() -> None:
        text = "\n\n".join(b for b in blocks if b.strip()).strip()
        if text:
            sections.append(
                {
                    "id": f"sec-{len(sections) + 1}",
                    "section_path": current_heading,
                    "page_or_anchor": current_anchor,
                    "text": text,
                }
            )
        blocks.clear()

    for elem in root.find_all(["h1", "h2", "h3", "p", "ul", "ol", "table"], recursive=True):
        if elem.find_parent("table") and elem.name != "table":
            continue
        parent_list = elem.find_parent(["ul", "ol"])
        if parent_list and elem.name != parent_list.name:
            continue

        name = elem.name.lower()
        if name in {"h1", "h2", "h3"}:
            flush()
            current_heading = elem.get_text(" ", strip=True)
            elem_id = elem.get("id") or re.sub(r"[^a-z0-9]+", "-", current_heading.lower()).strip("-")[:60]
            current_anchor = f"#{elem_id or 'section'}"
        elif name == "table":
            tbl_lines = _html_table_to_md(elem)
            if tbl_lines:
                blocks.append("\n".join(tbl_lines))
        elif name in {"ul", "ol"}:
            list_lines: list[str] = []
            for idx, li in enumerate(elem.find_all("li", recursive=False), start=1):
                item_text = re.sub(r"\s+", " ", _html_inline_to_md(li)).strip()
                if not item_text:
                    continue
                prefix = f"{idx}." if name == "ol" else "-"
                list_lines.append(f"{prefix} {item_text}")
            if list_lines:
                blocks.append("\n".join(list_lines))
        else:
            para = re.sub(r"\s+", " ", _html_inline_to_md(elem)).strip()
            if para:
                blocks.append(para)

    flush()
    return sections


def _join_wrapped_lines(lines: list[str]) -> str:
    """Rejoin soft line wraps from PDF/plain text into clean paragraphs and bullets."""
    paras: list[str] = []
    buf: list[str] = []
    subclause_re = re.compile(r"^(\d+\.\d+\s+[^:]{2,70}:)\s*(.*)$")
    kv_re = re.compile(r"^(Triggers|Required|Required Routing|SLA|Effective Date|Document ID|Policy Title|Category|Owner)\s*:\s*(.+)$", re.I)

    def flush_buf() -> None:
        if buf:
            paras.append(" ".join(buf).strip())
            buf.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_buf()
            continue
        if line.startswith("- ") or line.startswith("• "):
            flush_buf()
            item = line[2:].strip()
            m_field = re.match(r"^([a-zA-Z0-9_&/+\- ]{2,45}):\s*(.+)$", item)
            if m_field:
                buf.append(f"- **{m_field.group(1).strip()}:** {m_field.group(2)}")
            else:
                buf.append(f"- {item}")
            continue

        m_sub = subclause_re.match(line)
        if m_sub:
            flush_buf()
            lead = f"**{m_sub.group(1)}**"
            rest = m_sub.group(2).strip()
            buf.append(f"{lead} {rest}".strip())
            continue

        m_kv = kv_re.match(line)
        if m_kv:
            flush_buf()
            buf.append(f"**{m_kv.group(1)}:** {m_kv.group(2)}")
            continue

        buf.append(line)

    flush_buf()
    return "\n\n".join(paras)


def _extract_readable_pdf_sections(policy_path: Path, doc_id: str) -> list[dict[str, Any]]:
    reader = PdfReader(str(policy_path))
    banner_re = re.compile(rf"^Northstar Cloud Labs, Inc\.\s*\|\s*{re.escape(doc_id)}\b.*$", re.I)
    footer_re = re.compile(rf"^{re.escape(doc_id)}\s*-\s*Page\s*\d+\s*$", re.I)
    section_re = re.compile(r"^Section\s+\d+\..+$")

    sections: list[dict[str, Any]] = []
    current_heading = "Document Overview"
    current_anchor = "p. 1"
    cur_lines: list[str] = []

    def flush() -> None:
        text = _join_wrapped_lines(cur_lines)
        if text:
            sections.append(
                {
                    "id": f"sec-{len(sections) + 1}",
                    "section_path": current_heading,
                    "page_or_anchor": current_anchor,
                    "text": text,
                }
            )
        cur_lines.clear()

    in_title_wrap = False
    for page_num, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        for raw_line in txt.splitlines():
            line = raw_line.strip()
            if not line or banner_re.match(line) or footer_re.match(line):
                continue
            if line.upper().startswith(f"{doc_id}:"):
                in_title_wrap = True
                continue
            if in_title_wrap:
                if line.lower().startswith("document id:"):
                    in_title_wrap = False
                else:
                    continue
            if "|" in line and re.search(r"Document ID:|Category:|Effective Date:", line, re.I):
                for part in [p.strip() for p in line.split("|") if p.strip()]:
                    if ":" in part:
                        k, v = part.split(":", 1)
                        cur_lines.append(f"- **{k.strip()}:** {v.strip()}")
                continue
            if re.match(r"^(Owner)\s*:\s*.+$", line, re.I):
                k, v = line.split(":", 1)
                cur_lines.append(f"- **{k.strip()}:** {v.strip()}")
                continue
            if section_re.match(line):
                flush()
                current_heading = line
                current_anchor = f"p. {page_num}"
            else:
                cur_lines.append(line)

    flush()
    return sections


def _format_readable_txt_sections(parsed_sections: list[Any], doc_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, sec in enumerate(parsed_sections, start=1):
        lines = [ln.strip() for ln in sec.text.splitlines()]
        if idx == 1 and lines and lines[0].upper().startswith(f"{doc_id}:"):
            lines = lines[1:]
        formatted_lines: list[str] = []
        for ln in lines:
            if not ln:
                formatted_lines.append("")
            elif ln == sec.section_path and formatted_lines == []:
                continue
            elif re.match(r"^(Document ID|Policy Title|Category|Effective Date|Owner)\s*:\s*.+$", ln, re.I):
                k, v = ln.split(":", 1)
                formatted_lines.append(f"- **{k.strip()}:** {v.strip()}")
            elif ln.startswith("- "):
                item = ln[2:].strip()
                m_field = re.match(r"^([a-zA-Z0-9_ ]{2,35}):\s*(.+)$", item)
                formatted_lines.append(
                    f"- **{m_field.group(1)}:** {m_field.group(2)}" if m_field else f"- {item}"
                )
            else:
                formatted_lines.append(ln)
        text = _join_wrapped_lines(formatted_lines)
        out.append(
            {
                "id": f"sec-{idx}",
                "section_path": sec.section_path,
                "page_or_anchor": sec.page_or_anchor,
                "text": text,
            }
        )
    return out


def _build_readable_sections(policy_path: Path, doc_id: str, fmt: str) -> list[dict[str, Any]]:
    if fmt == "html":
        return _extract_readable_html_sections(policy_path)
    if fmt == "pdf":
        return _extract_readable_pdf_sections(policy_path, doc_id)
    _, parsed_sections = parse_policy_file(policy_path)
    if fmt == "txt":
        return _format_readable_txt_sections(parsed_sections, doc_id)
    return [
        {
            "id": f"sec-{idx}",
            "section_path": sec.section_path,
            "page_or_anchor": sec.page_or_anchor,
            "text": sec.text,
        }
        for idx, sec in enumerate(parsed_sections, start=1)
    ]


@app.get("/api/corpus")
async def list_corpus_documents() -> dict[str, Any]:
    """Return metadata, format breakdown, and chunk counts for all indexed policies."""
    settings = app.state.settings
    manifest = app.state.rag_manifest
    docs = manifest.get("documents", [])
    format_counts: dict[str, int] = {"html": 0, "pdf": 0, "markdown": 0, "txt": 0}
    enriched: list[dict[str, Any]] = []
    for doc in docs:
        fmt = str(doc.get("file_format", "")).lower()
        if fmt in format_counts:
            format_counts[fmt] += 1
        doc_id = str(doc.get("doc_id", "")).upper()
        enriched.append(
            {
                "doc_id": doc_id,
                "doc_title": _clean_doc_title(doc_id, str(doc.get("doc_title", ""))),
                "source_file": doc.get("source_file", ""),
                "file_format": fmt,
                "category": doc.get("category", ""),
                "category_label": _humanize_category(str(doc.get("category", ""))),
                "chunks": int(doc.get("chunks", 0)),
            }
        )
    return {
        "doc_count": manifest.get("doc_count", len(enriched)),
        "chunk_count": manifest.get("chunk_count", sum(d["chunks"] for d in enriched)),
        "embedding_provider": manifest.get("embedding_provider", "hash"),
        "embedding_model": manifest.get("embedding_model", "signed-ngram-hash"),
        "chunk_size_words": manifest.get("chunk_size_words", settings.chunk_size_words),
        "chunk_overlap_words": manifest.get("chunk_overlap_words", settings.chunk_overlap_words),
        "format_counts": format_counts,
        "documents": enriched,
    }


@app.get("/api/corpus/{doc_id}")
async def get_corpus_document(doc_id: str) -> dict[str, Any]:
    """Return full readable policy sections and exact indexed chunks for one Document ID."""
    settings = app.state.settings
    manifest = app.state.rag_manifest
    target_id = doc_id.strip().upper()
    doc_meta = next(
        (d for d in manifest.get("documents", []) if str(d.get("doc_id", "")).upper() == target_id),
        None,
    )
    if doc_meta is None:
        raise HTTPException(status_code=404, detail=f"Policy '{doc_id}' was not found.")

    db_path = settings.rag_index_dir / "chunks.db"
    chunks: list[dict[str, Any]] = []
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT chunk_idx, chunk_id, section_path, page_or_anchor, word_count, text
                FROM chunks
                WHERE UPPER(doc_id) = ?
                ORDER BY chunk_idx ASC
                """,
                (target_id,),
            ).fetchall()
            chunks = [
                {
                    "index": idx,
                    "chunk_idx": int(r["chunk_idx"]),
                    "chunk_id": r["chunk_id"],
                    "section_path": r["section_path"],
                    "page_or_anchor": r["page_or_anchor"],
                    "word_count": int(r["word_count"]),
                    "text": r["text"],
                }
                for idx, r in enumerate(rows, start=1)
            ]
        finally:
            conn.close()

    fmt = str(doc_meta.get("file_format", "")).lower()
    sections_out: list[dict[str, Any]] = []
    source_file = str(doc_meta.get("source_file", ""))
    policy_path = settings.policies_dir / Path(source_file).name
    if policy_path.exists():
        sections_out = _build_readable_sections(policy_path, target_id, fmt)
    else:
        for idx, ch in enumerate(chunks, start=1):
            sections_out.append(
                {
                    "id": f"sec-{idx}",
                    "section_path": ch["section_path"],
                    "page_or_anchor": ch["page_or_anchor"],
                    "text": ch["text"],
                }
            )

    return {
        "doc_id": target_id,
        "doc_title": _clean_doc_title(target_id, str(doc_meta.get("doc_title", ""))),
        "source_file": source_file,
        "file_format": fmt,
        "category": doc_meta.get("category", ""),
        "category_label": _humanize_category(str(doc_meta.get("category", ""))),
        "chunk_count": len(chunks) or int(doc_meta.get("chunks", 0)),
        "sections": sections_out,
        "chunks": chunks,
    }


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Readiness probe reporting loaded RAG corpus metadata and live MCP connection."""
    settings = app.state.settings
    manifest = app.state.rag_manifest
    mcp_client: MCPClientManager = app.state.mcp_client
    tool_names = [t.name for t in mcp_client.discovered_tools]
    return {
        "status": "ok",
        "service": "northstar-hr-agentic-rag",
        "corpus_docs": manifest.get("doc_count", 0),
        "corpus_chunks": manifest.get("chunk_count", 0),
        "embedding_provider": manifest.get("embedding_provider", "hash"),
        "embedding_model": manifest.get("embedding_model", "signed-ngram-hash"),
        "llm_provider": settings.effective_llm_provider,
        "gemini_model": settings.gemini_model,
        "mcp_transport": settings.mcp_transport,
        "mcp_connected": mcp_client.is_connected,
        "mcp_tools": tool_names,
        "random_seed": settings.random_seed,
    }


@app.get("/demo-tasks")
async def get_demo_tasks() -> dict[str, Any]:
    """Return preloaded interactive demo scenarios and synthetic personas."""
    emp_data = json.loads(
        (PROJECT_ROOT / "mock_data" / "employees.json").read_text(encoding="utf-8")
    )
    personas = [
        {
            "employee_id": e["employee_id"],
            "name": e["name"],
            "role": e["role"],
            "employment_type": e["employment_type"],
            "security_tier": e["security_tier"],
            "standing": e["standing"],
        }
        for e in emp_data.get("employees", [])
    ]
    return {"demo_tasks": DEMO_TASKS, "personas": personas}


@app.get("/tickets")
async def list_mock_tickets() -> dict[str, Any]:
    """List current synthetic mock HR tickets (is_mock: true)."""
    store = MockHRDataStore(app.state.settings)
    return {"tickets": store.list_tickets()}


@app.post("/chat")
async def chat_endpoint(req: ChatRequest) -> dict[str, Any]:
    """Execute one guarded RAG + MCP agentic turn."""
    orchestrator: AgentOrchestrator = app.state.orchestrator
    try:
        return await orchestrator.handle_query(
            user_query=req.message,
            provider_override=req.provider_override,
            conversation_context=req.context,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent execution error: {exc}") from exc


@app.post("/confirm")
async def confirm_ticket_endpoint(req: ConfirmTicketRequest) -> dict[str, Any]:
    """Confirm and persist a proposed mock HR ticket via MCP `create_mock_hr_ticket`."""
    if not req.confirmed:
        raise HTTPException(
            status_code=400, detail="Explicit confirmation (`confirmed=true`) is required."
        )
    orchestrator: AgentOrchestrator = app.state.orchestrator
    result = await orchestrator.confirm_mock_ticket(req.proposed_ticket)
    if not result.get("ok"):
        raise HTTPException(
            status_code=500, detail=f"Ticket persistence failed: {result.get('result')}"
        )
    return result
