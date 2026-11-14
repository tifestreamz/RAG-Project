"""End-to-end Agentic HR Policy & Operations orchestrator using MCPClientManager."""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from agent.guardrails import check_input_guardrails
from agent.llm_client import AgentTurnResult, GeminiAgentRunner, MockAgentRunner
from app_config import Settings, get_settings
from mcp_server.client import MCPClientManager

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Coordinates input guardrails, Gemini/Mock runner selection, MCP tool execution, and confirmation."""

    def __init__(
        self,
        mcp_client: MCPClientManager,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.mcp_client = mcp_client
        self._mock_runner = MockAgentRunner(self.settings)
        self._gemini_runner: GeminiAgentRunner | None = None

    def _get_gemini_runner(self) -> GeminiAgentRunner:
        if self._gemini_runner is None:
            self._gemini_runner = GeminiAgentRunner(self.settings)
        return self._gemini_runner

    async def handle_query(
        self,
        user_query: str,
        provider_override: Literal["auto", "gemini", "mock"] | None = None,
    ) -> dict[str, Any]:
        """Execute a full guarded RAG + MCP agent turn and return structured response + trace."""
        t0 = time.perf_counter()
        guard = check_input_guardrails(user_query)

        if guard.blocked or guard.clarification_needed or guard.out_of_scope:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            status = (
                "blocked"
                if guard.blocked
                else ("abstained" if guard.out_of_scope else "clarification_needed")
            )
            return {
                "answer": guard.safe_message,
                "mode_used": "guardrail",
                "status": status,
                "guardrail_flags": guard.flags,
                "trace": [],
                "citations": [],
                "draft_email": None,
                "pending_confirmation": None,
                "escalation": None,
                "abstained": guard.blocked or guard.out_of_scope,
                "ui_context": {},
                "latency_ms": latency_ms,
            }

        provider = (
            self.settings.effective_llm_provider
            if provider_override in {None, "auto"}
            else provider_override
        )
        if provider == "gemini" and not self.settings.has_valid_gemini_key:
            provider = "mock"

        turn: AgentTurnResult
        fallback_flags = list(guard.flags)
        if provider == "gemini":
            try:
                turn = await self._get_gemini_runner().run_turn(
                    user_query=user_query,
                    mcp_client=self.mcp_client,
                    resolved_employee_id=guard.resolved_employee_id,
                    is_p1_ethics=guard.is_p1_ethics,
                )
            except Exception as exc:
                logger.warning("Gemini run failed (%s); falling back to mock runner", exc)
                fallback_flags.append("gemini_fallback_to_mock")
                turn = await self._mock_runner.run_turn(
                    user_query=user_query,
                    mcp_client=self.mcp_client,
                    resolved_employee_id=guard.resolved_employee_id,
                    is_p1_ethics=guard.is_p1_ethics,
                )
        else:
            turn = await self._mock_runner.run_turn(
                user_query=user_query,
                mcp_client=self.mcp_client,
                resolved_employee_id=guard.resolved_employee_id,
                is_p1_ethics=guard.is_p1_ethics,
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "answer": turn.answer,
            "mode_used": turn.mode_used,
            "status": "abstained" if turn.abstained else "completed",
            "guardrail_flags": fallback_flags,
            "trace": turn.trace,
            "citations": turn.citations,
            "draft_email": turn.draft_email,
            "pending_confirmation": turn.pending_confirmation,
            "escalation": turn.escalation,
            "abstained": turn.abstained,
            "ui_context": turn.ui_context,
            "latency_ms": latency_ms,
        }

    async def confirm_mock_ticket(self, proposed_ticket: dict[str, Any]) -> dict[str, Any]:
        """Persist a previously previewed mock HR ticket via MCP `create_mock_hr_ticket`."""
        t0 = time.perf_counter()
        args = {
            "employee_id": proposed_ticket.get("employee_id", ""),
            "category": proposed_ticket.get("category", "general"),
            "priority": proposed_ticket.get("priority", "P2"),
            "summary": proposed_ticket.get("summary", ""),
            "policy_references": proposed_ticket.get("policy_references", []),
            "confirmed": True,
        }
        call_res = await self.mcp_client.call_tool("create_mock_hr_ticket", args)
        return {
            "ok": call_res["ok"],
            "result": call_res["result"],
            "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }
