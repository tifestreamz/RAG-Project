"""FastAPI application wiring MCPClientManager, AgentOrchestrator, and SPA UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

    sections_out: list[dict[str, Any]] = []
    source_file = str(doc_meta.get("source_file", ""))
    policy_path = settings.policies_dir / Path(source_file).name
    if policy_path.exists():
        _, parsed_sections = parse_policy_file(policy_path)
        for idx, sec in enumerate(parsed_sections, start=1):
            sections_out.append(
                {
                    "id": f"sec-{idx}",
                    "section_path": sec.section_path,
                    "page_or_anchor": sec.page_or_anchor,
                    "text": sec.text,
                }
            )
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

    fmt = str(doc_meta.get("file_format", "")).lower()
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
