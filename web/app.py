"""FastAPI application wiring MCPClientManager, AgentOrchestrator, and SPA UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
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
from rag.ingest import build_index

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
