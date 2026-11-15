"""End-to-end Agentic HR Policy & Operations orchestrator using MCPClientManager."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Literal

from agent.guardrails import (
    check_input_guardrails,
    has_explicit_ticket_intent,
    is_bare_ticket_request,
)
from agent.llm_client import AgentTurnResult, GeminiAgentRunner, MockAgentRunner
from app_config import Settings, get_settings
from mcp_server.client import MCPClientManager

logger = logging.getLogger(__name__)

_FOLLOW_UP_REF_RE = re.compile(
    r"\b(?:this|that|it|them|him|her|they|above|previous|same)\b",
    re.I,
)


def _resolve_follow_up_context(
    user_query: str,
    resolved_employee_id: str | None,
    conversation_context: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any] | None]:
    """Return `(is_follow_up, normalized_context)` when a turn refers to prior UI context."""
    ctx = conversation_context or {}
    if not ctx or resolved_employee_id is not None:
        return False, None
    has_anchor = bool(ctx.get("employee_id") or ctx.get("previous_query"))
    if not has_anchor:
        return False, None
    is_ref = bool(
        _FOLLOW_UP_REF_RE.search(user_query) or has_explicit_ticket_intent(user_query)
    )
    return (is_ref, ctx if is_ref else None)


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
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a full guarded RAG + MCP agent turn and return structured response + trace."""
        t0 = time.perf_counter()
        guard = check_input_guardrails(user_query)

        if guard.blocked or guard.out_of_scope:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            status = "blocked" if guard.blocked else "abstained"
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
                "abstained": True,
                "ui_context": {},
                "latency_ms": latency_ms,
            }

        is_follow_up, active_ctx = _resolve_follow_up_context(
            user_query, guard.resolved_employee_id, conversation_context
        )
        raw_ctx_emp = str((active_ctx or {}).get("employee_id") or "").strip().upper()
        ctx_emp_id = raw_ctx_emp if raw_ctx_emp and raw_ctx_emp != "EMP-UNKNOWN" else None

        if guard.clarification_needed and not is_follow_up:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "answer": guard.safe_message,
                "mode_used": "guardrail",
                "status": "clarification_needed",
                "guardrail_flags": guard.flags,
                "trace": [],
                "citations": [],
                "draft_email": None,
                "pending_confirmation": None,
                "escalation": None,
                "abstained": False,
                "ui_context": {},
                "latency_ms": latency_ms,
            }

        if not is_follow_up and is_bare_ticket_request(user_query):
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "answer": (
                    "### Clarification Needed\n"
                    "- To prepare an HR ticket preview, please specify:\n"
                    "  1. **Employee ID or Name** (e.g., `EMP-1042` Maya Lin, `EMP-1018` Carlos Vega, "
                    "`EMP-1089` Jordan Brooks), or indicate if it is a **confidential P1 ethics report**.\n"
                    "  2. **The request or issue** to log (e.g., PTO dates, remote work destination, or expense item)."
                ),
                "mode_used": "guardrail",
                "status": "clarification_needed",
                "guardrail_flags": ["missing_ticket_details"],
                "trace": [],
                "citations": [],
                "draft_email": None,
                "pending_confirmation": None,
                "escalation": None,
                "abstained": False,
                "ui_context": {},
                "latency_ms": latency_ms,
            }

        resolved_emp = guard.resolved_employee_id or ctx_emp_id
        effective_p1 = guard.is_p1_ethics or bool((active_ctx or {}).get("is_p1_ethics"))
        prev_q = str((active_ctx or {}).get("previous_query") or "").strip()
        mock_query = (
            f"{prev_q} — {user_query}"
            if (is_follow_up and prev_q and prev_q.lower() not in user_query.lower())
            else user_query
        )

        provider = (
            self.settings.effective_llm_provider
            if provider_override in {None, "auto"}
            else provider_override
        )
        if provider == "gemini" and not self.settings.has_valid_gemini_key:
            provider = "mock"

        turn: AgentTurnResult
        fallback_flags = list(guard.flags)
        if effective_p1 and "p1_confidential_ethics" not in fallback_flags:
            fallback_flags.append("p1_confidential_ethics")
        if provider == "gemini":
            try:
                turn = await self._get_gemini_runner().run_turn(
                    user_query=user_query,
                    mcp_client=self.mcp_client,
                    resolved_employee_id=resolved_emp,
                    is_p1_ethics=effective_p1,
                    prior_context=active_ctx,
                )
            except Exception as exc:
                logger.warning("Gemini run failed (%s); falling back to mock runner", exc)
                fallback_flags.append("gemini_fallback_to_mock")
                turn = await self._mock_runner.run_turn(
                    user_query=mock_query,
                    mcp_client=self.mcp_client,
                    resolved_employee_id=resolved_emp,
                    is_p1_ethics=effective_p1,
                    prior_context=active_ctx,
                )
        else:
            turn = await self._mock_runner.run_turn(
                user_query=mock_query,
                mcp_client=self.mcp_client,
                resolved_employee_id=resolved_emp,
                is_p1_ethics=effective_p1,
                prior_context=active_ctx,
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
