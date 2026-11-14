"""LLM Agent Runners: Live Gemini Interactions API (`gemini-3.5-flash-lite`) and deterministic Mock MCP Runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any

from agent.guardrails import (
    sanitize_tool_arguments,
    summarize_tool_output,
)
from app_config import Settings, get_settings
from mcp_server.client import DiscoveredTool, MCPClientManager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Northstar Cloud Labs HR Policy & Operations Agent.
Follow these strict rules:
1. NEVER invent company policy rules, dollar caps, day limits, employee balances, or document IDs. Always invoke the discovered MCP tools (`search_policy_documents`, `get_policy_section`, `lookup_employee_profile`, `check_pto_balance`, `lookup_benefits_status`, `check_policy_compliance`, `draft_hr_email`, `create_mock_hr_ticket`) to obtain facts.
2. When evaluating an employee request, call the relevant lookup tools and `check_policy_compliance` BEFORE drafting communications or recommending approvals.
3. Only call `create_mock_hr_ticket` with `confirmed=false` (preview mode). Never claim a ticket was persisted or an external email was actually sent.
4. For P1 harassment, retaliation, discrimination, or safety escalations (`POL-010`, `POL-011`), NEVER recommend CCing a direct manager if the manager may be involved; route strictly to `ethics@northstarcloud.example`.
5. If `search_policy_documents` indicates `below_threshold=true` or returns no relevant Northstar policy evidence, politely abstain and state that the request is outside Northstar Cloud Labs' indexed HR policies.
6. Format EVERY policy/workflow response using these two markdown headings:
### Policy Facts (Cited)
(Bullet points grounded strictly in retrieved policy snippets and HR records, each citing `[POL-XXX | Section ...]`)
### Recommended Next Steps
(Clear approval path, compliance outcome, draft/ticket confirmation guidance, or escalation SLA)"""

CITY_TO_COUNTRY: dict[str, str] = {
    "lisbon": "Portugal",
    "porto": "Portugal",
    "portugal": "Portugal",
    "madrid": "Spain",
    "barcelona": "Spain",
    "spain": "Spain",
    "paris": "France",
    "france": "France",
    "berlin": "Germany",
    "munich": "Germany",
    "germany": "Germany",
    "amsterdam": "Netherlands",
    "netherlands": "Netherlands",
    "dublin": "Ireland",
    "ireland": "Ireland",
    "rome": "Italy",
    "milan": "Italy",
    "italy": "Italy",
    "london": "United Kingdom",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "toronto": "Canada",
    "montreal": "Canada",
    "vancouver": "Canada",
    "canada": "Canada",
    "tokyo": "Japan",
    "japan": "Japan",
    "sydney": "Australia",
    "australia": "Australia",
    "mexico": "Mexico",
    "costa rica": "Costa Rica",
    "russia": "Russia",
    "moscow": "Russia",
    "belarus": "Belarus",
    "iran": "Iran",
    "north korea": "North Korea",
    "syria": "Syria",
    "cuba": "Cuba",
    "china": "China",
    "beijing": "China",
    "shanghai": "China",
    "thailand": "Thailand",
    "bangkok": "Thailand",
    "brazil": "Brazil",
}


@dataclass(slots=True)
class AgentTurnResult:
    """Structured output returned by either Gemini or Mock agent runners."""

    answer: str
    mode_used: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    draft_email: dict[str, Any] | None = None
    pending_confirmation: dict[str, Any] | None = None
    escalation: dict[str, Any] | None = None
    abstained: bool = False
    ui_context: dict[str, Any] = field(default_factory=dict)


def _collect_artifacts_from_tool_call(
    tool_name: str,
    payload: dict[str, Any],
    citations_map: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> list[str]:
    """Update citations, email drafts, pending ticket confirmations, and escalations."""
    step_citations: list[str] = []
    ui_ctx: dict[str, Any] = state.setdefault("ui_context", {})
    if tool_name == "search_policy_documents":
        for hit in payload.get("hits", []):
            cid = hit.get("chunk_id", "")
            label = f"{hit.get('doc_id')} | {hit.get('section_path')}"
            step_citations.append(label)
            if cid and cid not in citations_map:
                citations_map[cid] = {
                    "chunk_id": cid,
                    "doc_id": hit.get("doc_id"),
                    "doc_title": hit.get("doc_title"),
                    "source_file": hit.get("source_file"),
                    "file_format": hit.get("file_format"),
                    "section_path": hit.get("section_path"),
                    "page_or_anchor": hit.get("page_or_anchor"),
                    "snippet": hit.get("snippet"),
                    "rrf_score": hit.get("rrf_score"),
                }
        state["last_below_threshold"] = bool(payload.get("below_threshold", False))
        if not state["last_below_threshold"] and payload.get("hits"):
            state["any_in_threshold_hit"] = True
    elif tool_name == "get_policy_section" and payload.get("found"):
        for sec in payload.get("sections", [])[:3]:
            cid = sec.get("chunk_id", "")
            label = f"{payload.get('doc_id')} | {sec.get('section_path')}"
            step_citations.append(label)
            if cid and cid not in citations_map:
                citations_map[cid] = {
                    "chunk_id": cid,
                    "doc_id": payload.get("doc_id"),
                    "doc_title": payload.get("doc_title"),
                    "source_file": payload.get("source_file"),
                    "file_format": "section_lookup",
                    "section_path": sec.get("section_path"),
                    "page_or_anchor": sec.get("page_or_anchor"),
                    "snippet": " ".join(sec.get("text", "").split())[:340],
                    "rrf_score": 1.0,
                }
            state["any_in_threshold_hit"] = True
    elif tool_name == "lookup_employee_profile" and payload.get("found") and payload.get("employee"):
        ui_ctx["employee"] = payload["employee"]
    elif tool_name == "check_pto_balance" and payload.get("found") and payload.get("pto_balance"):
        ui_ctx["pto_balance"] = payload["pto_balance"]
    elif tool_name == "lookup_benefits_status" and payload.get("found") and payload.get("benefits"):
        ui_ctx["benefits"] = payload["benefits"]
    elif tool_name == "check_policy_compliance" and payload.get("found"):
        for ref in payload.get("policy_citations", []):
            step_citations.append(ref)
        status = payload.get("status")
        prio = payload.get("recommended_priority", "P3")
        ui_ctx["compliance"] = {
            "request_type": payload.get("request_type"),
            "status": status,
            "eligible": payload.get("eligible"),
            "recommended_priority": prio,
            "metrics": payload.get("metrics", {}),
            "violations": payload.get("violations", []),
            "warnings": payload.get("warnings", []),
            "required_approvers": payload.get("required_approvers", []),
            "policy_citations": payload.get("policy_citations", []),
        }
        if status in {"NON_COMPLIANT", "ESCALATION_REQUIRED"} or prio in {"P1", "P2"}:
            state["escalation"] = {
                "recommended": True,
                "priority": prio,
                "status": status,
                "routing": payload.get("required_approvers", []),
                "reasons": payload.get("violations") or payload.get("warnings", []),
            }
    elif tool_name == "draft_hr_email":
        state["draft_email"] = payload.get("draft")
    elif tool_name == "create_mock_hr_ticket" and payload.get("proposed_ticket"):
        state["pending_confirmation"] = payload.get("proposed_ticket")
        if state.get("escalation") is None:
            prop = payload["proposed_ticket"]
            state["escalation"] = {
                "recommended": True,
                "priority": prop.get("priority", "P2"),
                "status": "PENDING_CONFIRMATION",
                "routing": ["People Operations Queue"],
                "reasons": [prop.get("summary", "")],
            }
    return step_citations


class GeminiAgentRunner:
    """Stateless Gemini 3.5 Flash-Lite Interactions API agent driving live MCP tools."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        from google import genai

        self.client = genai.Client(api_key=self.settings.gemini_api_key)

    async def _create_interaction(
        self,
        history: list[dict[str, Any]],
        tool_decls: list[dict[str, Any]],
    ) -> Any:
        def _call() -> Any:
            return self.client.interactions.create(
                model=self.settings.gemini_model,
                store=False,
                input=history,
                system_instruction=SYSTEM_PROMPT,
                tools=tool_decls,
            )

        for attempt in range(2):
            try:
                return await asyncio.wait_for(asyncio.to_thread(_call), timeout=45.0)
            except Exception as exc:
                if attempt == 0:
                    logger.warning("Gemini interaction attempt 1 failed (%s); retrying", exc)
                    await asyncio.sleep(1.0)
                else:
                    raise

    async def run_turn(
        self,
        user_query: str,
        mcp_client: MCPClientManager,
        resolved_employee_id: str | None = None,
        is_p1_ethics: bool = False,
    ) -> AgentTurnResult:
        discovered: list[DiscoveredTool] = await mcp_client.list_tools()
        tool_decls = [t.to_gemini_declaration() for t in discovered]

        prompt_text = user_query
        if resolved_employee_id and resolved_employee_id not in user_query.upper():
            prompt_text = f"{user_query}\n[Resolved Employee ID: {resolved_employee_id}]"
        if is_p1_ethics:
            prompt_text += "\n[Safety Flag: Potential P1 Harassment/Retaliation report — follow POL-010/POL-011 confidentiality rules strictly.]"

        history: list[dict[str, Any]] = [
            {"type": "user_input", "content": [{"type": "text", "text": prompt_text}]}
        ]

        trace: list[dict[str, Any]] = []
        citations_map: dict[str, dict[str, Any]] = {}
        state: dict[str, Any] = {
            "draft_email": None,
            "pending_confirmation": None,
            "escalation": None,
            "last_below_threshold": False,
            "any_in_threshold_hit": False,
        }
        final_text = ""

        for _ in range(self.settings.max_agent_steps):
            interaction = await self._create_interaction(history, tool_decls)
            steps = getattr(interaction, "steps", None) or []
            function_calls = []
            for step in steps:
                step_type = getattr(step, "type", "")
                # Keep `thought` steps (with required `signature`) in API `history` for store=False
                # multi-step tool calls; `trace` below records only executed tool calls.
                if hasattr(step, "model_dump"):
                    history.append(step.model_dump(exclude_none=True))
                if step_type == "function_call":
                    function_calls.append(step)

            if not function_calls:
                final_text = (getattr(interaction, "output_text", None) or "").strip()
                break

            for fc in function_calls:
                args = sanitize_tool_arguments(fc.name, dict(fc.arguments or {}))
                call_res = await mcp_client.call_tool(fc.name, args)
                payload = call_res["result"]
                step_cites = _collect_artifacts_from_tool_call(
                    fc.name, payload, citations_map, state
                )
                trace.append(
                    {
                        "step": len(trace) + 1,
                        "tool_name": fc.name,
                        "arguments": args,
                        "output_summary": summarize_tool_output(fc.name, payload),
                        "citations": step_cites,
                        "duration_ms": call_res["duration_ms"],
                        "status": "ok" if call_res["ok"] else "error",
                    }
                )
                history.append(
                    {
                        "type": "function_result",
                        "call_id": fc.id,
                        "name": fc.name,
                        "is_error": not call_res["ok"],
                        "result": [{"type": "text", "text": json.dumps(payload)}],
                    }
                )
        else:
            final_text = (
                "### Policy Facts (Cited)\n- Reached maximum autonomous planning steps; "
                "partial findings were gathered via MCP tools.\n\n"
                "### Recommended Next Steps\n- Review the trace panel or narrow the request."
            )

        abstained = (
            not resolved_employee_id
            and not is_p1_ethics
            and bool(state["last_below_threshold"])
            and not bool(state["any_in_threshold_hit"])
        )
        return AgentTurnResult(
            answer=final_text,
            mode_used="gemini",
            trace=trace,
            citations=list(citations_map.values()),
            draft_email=state["draft_email"],
            pending_confirmation=state["pending_confirmation"],
            escalation=state["escalation"],
            abstained=abstained,
            ui_context=state.get("ui_context", {}),
        )


def _extract_notice_days(text: str) -> tuple[int | None, str]:
    """Parse advance-notice duration and return text with notice phrase removed."""
    m_weeks = re.search(
        r"(\d+)\s*-?\s*weeks?(?:'s|s')?\s+(?:advance\s+)?notice", text, re.I
    )
    if m_weeks:
        days = int(m_weeks.group(1)) * 5
        cleaned = text[: m_weeks.start()] + " " + text[m_weeks.end() :]
        return days, cleaned

    m_days = re.search(
        r"(\d+)\s*(?:business|calendar)?\s*days?\s+(?:of\s+)?(?:advance\s+)?notice",
        text,
        re.I,
    )
    if m_days:
        days = int(m_days.group(1))
        cleaned = text[: m_days.start()] + " " + text[m_days.end() :]
        return days, cleaned
    return None, text


def _extract_requested_days(text: str) -> float:
    m_weeks = re.search(r"(\d+(?:\.\d+)?)\s*-?\s*weeks?\b", text, re.I)
    if m_weeks:
        return round(float(m_weeks.group(1)) * 7.0, 1)
    m_days = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:consecutive\s+)?(?:calendar\s+|business\s+|pto\s+|remote\s+)?days?\b",
        text,
        re.I,
    )
    if m_days:
        return float(m_days.group(1))
    return 0.0


def _extract_country(text: str) -> str:
    lower = text.lower()
    for key, country in CITY_TO_COUNTRY.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return country
    return ""


def _extract_usd(text: str) -> float:
    matches = re.findall(r"\$\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not matches:
        return 0.0
    return round(sum(float(m.replace(",", "")) for m in matches), 2)


class MockAgentRunner:
    """Deterministic zero-cost MCP Agent Runner for offline CI/CD and demos."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def _exec(
        self,
        mcp_client: MCPClientManager,
        tool_name: str,
        arguments: dict[str, Any],
        trace: list[dict[str, Any]],
        citations_map: dict[str, dict[str, Any]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        args = sanitize_tool_arguments(tool_name, arguments)
        call_res = await mcp_client.call_tool(tool_name, args)
        payload = call_res["result"]
        step_cites = _collect_artifacts_from_tool_call(
            tool_name, payload, citations_map, state
        )
        trace.append(
            {
                "step": len(trace) + 1,
                "tool_name": tool_name,
                "arguments": args,
                "output_summary": summarize_tool_output(tool_name, payload),
                "citations": step_cites,
                "duration_ms": call_res["duration_ms"],
                "status": "ok" if call_res["ok"] else "error",
            }
        )
        return payload

    async def run_turn(
        self,
        user_query: str,
        mcp_client: MCPClientManager,
        resolved_employee_id: str | None = None,
        is_p1_ethics: bool = False,
    ) -> AgentTurnResult:
        # Discover tools dynamically over real MCP ClientSession
        await mcp_client.list_tools()

        trace: list[dict[str, Any]] = []
        citations_map: dict[str, dict[str, Any]] = {}
        state: dict[str, Any] = {
            "draft_email": None,
            "pending_confirmation": None,
            "escalation": None,
            "last_below_threshold": False,
            "any_in_threshold_hit": False,
        }

        if is_p1_ethics:
            return await self._run_p1_ethics_workflow(
                user_query, resolved_employee_id, mcp_client, trace, citations_map, state
            )

        if resolved_employee_id:
            return await self._run_employee_workflow(
                user_query, resolved_employee_id, mcp_client, trace, citations_map, state
            )

        return await self._run_policy_qa(
            user_query, mcp_client, trace, citations_map, state
        )

    async def _run_p1_ethics_workflow(
        self,
        user_query: str,
        emp_id: str | None,
        mcp_client: MCPClientManager,
        trace: list[dict[str, Any]],
        citations_map: dict[str, dict[str, Any]],
        state: dict[str, Any],
    ) -> AgentTurnResult:
        await self._exec(
            mcp_client,
            "search_policy_documents",
            {
                "query": f"{user_query} harassment retaliation P1 confidential ethics",
                "top_k": 5,
                "category": "conduct",
            },
            trace,
            citations_map,
            state,
        )
        target_emp = emp_id or "EMP-1042"
        if emp_id:
            await self._exec(
                mcp_client,
                "lookup_employee_profile",
                {"employee_id": emp_id},
                trace,
                citations_map,
                state,
            )
            await self._exec(
                mcp_client,
                "check_policy_compliance",
                {"employee_id": emp_id, "request_type": "ethics_escalation"},
                trace,
                citations_map,
                state,
            )
        await self._exec(
            mcp_client,
            "draft_hr_email",
            {
                "recipient": "ethics@northstarcloud.example",
                "cc_list": [],
                "subject": f"[CONFIDENTIAL P1] Ethics & Conduct Escalation ({target_emp})",
                "body": (
                    "CONFIDENTIAL PRIORITY P1 REPORT (SLA: 4 Business Hours)\n"
                    f"Reference Employee: {emp_id or 'Unspecified / Confidential Reporter'}\n"
                    f"Summary: {user_query[:300]}\n\n"
                    "Per POL-010 and POL-011 Sec 2.1, the direct manager has NOT been "
                    "copied to preserve strict anti-retaliation confidentiality."
                ),
            },
            trace,
            citations_map,
            state,
        )
        await self._exec(
            mcp_client,
            "create_mock_hr_ticket",
            {
                "employee_id": target_emp,
                "category": "ethics_confidential",
                "priority": "P1",
                "summary": f"Confidential P1 Ethics/Conduct Escalation: {user_query[:180]}",
                "policy_references": ["POL-010", "POL-011"],
                "confirmed": False,
            },
            trace,
            citations_map,
            state,
        )
        answer = (
            "### Policy Facts (Cited)\n"
            "- Northstar enforces a zero-tolerance anti-harassment and anti-retaliation policy "
            "(`[POL-010 | Anti-Harassment & Non-Retaliation]`).\n"
            "- Allegations involving harassment, discrimination, or manager retaliation trigger "
            "**Priority P1 (4-business-hour SLA)** routing strictly to the Confidential People Operations "
            "& Ethics Queue (`ethics@northstarcloud.example`) (`[POL-011 | Section 2.1]`).\n"
            "- Direct managers must **never** be copied or notified when they may be implicated or "
            "when confidentiality could be jeopardized (`[POL-011 | Section 2.1]`).\n\n"
            "### Recommended Next Steps\n"
            "- A confidential draft email addressed solely to `ethics@northstarcloud.example` (no manager CC) "
            "has been prepared.\n"
            "- Click **Confirm & Create Mock HR Ticket** to log a synthetic **P1** confidential case "
            "previewed below."
        )
        return AgentTurnResult(
            answer=answer,
            mode_used="mock",
            trace=trace,
            citations=list(citations_map.values()),
            draft_email=state["draft_email"],
            pending_confirmation=state["pending_confirmation"],
            escalation=state["escalation"],
            abstained=False,
            ui_context=state.get("ui_context", {}),
        )

    async def _run_employee_workflow(
        self,
        user_query: str,
        emp_id: str,
        mcp_client: MCPClientManager,
        trace: list[dict[str, Any]],
        citations_map: dict[str, dict[str, Any]],
        state: dict[str, Any],
    ) -> AgentTurnResult:
        emp_resp = await self._exec(
            mcp_client,
            "lookup_employee_profile",
            {"employee_id": emp_id},
            trace,
            citations_map,
            state,
        )
        if not emp_resp.get("found"):
            return AgentTurnResult(
                answer=(
                    "### Policy Facts (Cited)\n"
                    f"- No employee record was found for ID `{emp_id}` in Northstar's HR directory.\n\n"
                    "### Recommended Next Steps\n"
                    "- Verify the employee ID (`EMP-XXXX`, e.g., `EMP-1042`, `EMP-1018`, `EMP-1055`) "
                    "and re-submit your query."
                ),
                mode_used="mock",
                trace=trace,
                citations=[],
                abstained=True,
            )

        emp = emp_resp["employee"]
        lower = user_query.lower()
        notice_days, cleaned_text = _extract_notice_days(user_query)
        req_days = _extract_requested_days(cleaned_text)
        country = _extract_country(user_query)
        amount_usd = _extract_usd(user_query)
        during_blackout = any(
            k in lower
            for k in ("blackout", "release freeze", "coverage window", "managed coverage")
        )
        mentions_holidays = any(
            k in lower for k in ("december", "dec ", "winter recharge", "christmas", "holiday", "year-end")
        )

        is_intl = bool(country) or any(
            k in lower for k in ("workcation", "international", "abroad", "work from ")
        )
        wants_benefits = any(
            k in lower for k in ("benefit", "401k", "401(k)", "wellness", "stipend", "l&d", "tuition", "health", "budget")
        )
        wants_pto = any(
            k in lower for k in ("pto", "vacation", "time off", "leave", "floating", "holiday", "balance", "borrow", "negative")
        )

        pto_resp = await self._exec(
            mcp_client,
            "check_pto_balance",
            {"employee_id": emp_id},
            trace,
            citations_map,
            state,
        )
        ben_resp: dict[str, Any] | None = None
        if wants_benefits or not is_intl:
            ben_resp = await self._exec(
                mcp_client,
                "lookup_benefits_status",
                {"employee_id": emp_id},
                trace,
                citations_map,
                state,
            )

        # Policy retrieval
        if is_intl:
            await self._exec(
                mcp_client,
                "search_policy_documents",
                {
                    "query": f"temporary international remote work 30 days {country} Infosec {emp['security_tier']}",
                    "top_k": 4,
                    "category": "remote_work",
                },
                trace,
                citations_map,
                state,
            )
            await self._exec(
                mcp_client,
                "search_policy_documents",
                {
                    "query": f"remote access VPN MFA travel loaner laptop {emp['security_tier']}",
                    "top_k": 3,
                    "category": "security",
                },
                trace,
                citations_map,
                state,
            )
        else:
            await self._exec(
                mcp_client,
                "search_policy_documents",
                {"query": user_query, "top_k": 5},
                trace,
                citations_map,
                state,
            )
            if wants_pto:
                await self._exec(
                    mcp_client,
                    "search_policy_documents",
                    {
                        "query": "paid time off PTO accrual advance notice blackout",
                        "top_k": 3,
                        "doc_id": "POL-001",
                    },
                    trace,
                    citations_map,
                    state,
                )
            if mentions_holidays:
                await self._exec(
                    mcp_client,
                    "search_policy_documents",
                    {
                        "query": "Winter Recharge shutdown December holidays PTO deduction",
                        "top_k": 2,
                        "doc_id": "POL-002",
                    },
                    trace,
                    citations_map,
                    state,
                )

        comp_resp: dict[str, Any] | None = None
        if is_intl:
            comp_resp = await self._exec(
                mcp_client,
                "check_policy_compliance",
                {
                    "employee_id": emp_id,
                    "request_type": "international_remote_work",
                    "days_requested": req_days or 10.0,
                    "destination_country": country,
                    "advance_notice_days": notice_days,
                    "during_blackout": during_blackout,
                },
                trace,
                citations_map,
                state,
            )
        elif amount_usd > 0 or ("l&d" in lower and "budget" in lower):
            comp_resp = await self._exec(
                mcp_client,
                "check_policy_compliance",
                {
                    "employee_id": emp_id,
                    "request_type": "expense_or_ld",
                    "amount_usd": amount_usd,
                    "during_blackout": during_blackout,
                },
                trace,
                citations_map,
                state,
            )
        elif wants_pto and (req_days > 0 or "borrow" in lower or "blackout" in lower or emp.get("employment_type") == "Contractor" or not emp.get("probation_complete")):
            comp_resp = await self._exec(
                mcp_client,
                "check_policy_compliance",
                {
                    "employee_id": emp_id,
                    "request_type": "pto_request",
                    "days_requested": req_days or (3.0 if "borrow" in lower else 1.0),
                    "advance_notice_days": notice_days,
                    "during_blackout": during_blackout,
                },
                trace,
                citations_map,
                state,
            )

        # Draft approval / exception email + ticket preview when actionable workflow detected
        is_action_request = (
            is_intl
            or comp_resp is not None
            or any(k in lower for k in ("approve", "approval", "request", "draft", "email", "ticket", "plan", "wants to", "can "))
        )
        if is_action_request and comp_resp is not None:
            approvers = comp_resp.get("required_approvers", [])
            prio = comp_resp.get("recommended_priority", "P3")
            status = comp_resp.get("status", "CONDITIONAL_APPROVAL")
            cc_list = [f"{emp['manager_name']} (Direct Manager)"]
            if prio == "P2":
                cc_list.append("people-ops@northstarcloud.example")
            if is_intl:
                cc_list.append("infosec@northstarcloud.example")

            await self._exec(
                mcp_client,
                "draft_hr_email",
                {
                    "recipient": ", ".join(approvers[:2]) or "people-ops@northstarcloud.example",
                    "cc_list": list(dict.fromkeys(cc_list)),
                    "subject": f"[{prio} | {status}] HR Request for {emp['name']} ({emp['employee_id']})",
                    "body": self._build_draft_body(emp, comp_resp, pto_resp.get("pto_balance", {}), country, req_days),
                },
                trace,
                citations_map,
                state,
            )

            needs_ticket = (
                status == "NON_COMPLIANT"
                or prio in {"P1", "P2"}
                or bool(comp_resp.get("metrics", {}).get("requires_loaner_laptop"))
                or any(k in lower for k in ("ticket", "submit", "log case"))
            )
            if needs_ticket:
                category = "remote_work" if is_intl else ("pto_exception" if wants_pto else "expense")
                await self._exec(
                    mcp_client,
                    "create_mock_hr_ticket",
                    {
                        "employee_id": emp_id,
                        "category": category,
                        "priority": prio,
                        "summary": f"{status}: {emp['name']} ({emp_id}) — {user_query[:160]}",
                        "policy_references": [
                            c.split(" ")[0] for c in comp_resp.get("policy_citations", [])
                        ],
                        "confirmed": False,
                    },
                    trace,
                    citations_map,
                    state,
                )

        answer = self._format_employee_answer(
            emp=emp,
            pto=pto_resp.get("pto_balance", {}),
            benefits=ben_resp.get("benefits") if ben_resp else None,
            compliance=comp_resp,
            show_holidays=mentions_holidays,
            show_blackout=during_blackout or bool(pto_resp.get("pto_balance", {}).get("blackout_team_flag")),
            has_draft=state["draft_email"] is not None,
            has_ticket=state["pending_confirmation"] is not None,
        )
        return AgentTurnResult(
            answer=answer,
            mode_used="mock",
            trace=trace,
            citations=list(citations_map.values()),
            draft_email=state["draft_email"],
            pending_confirmation=state["pending_confirmation"],
            escalation=state["escalation"],
            abstained=False,
            ui_context=state.get("ui_context", {}),
        )

    @staticmethod
    def _build_draft_body(
        emp: dict[str, Any],
        comp: dict[str, Any],
        pto: dict[str, Any],
        country: str,
        req_days: float,
    ) -> str:
        lines = [
            f"Employee: {emp['name']} ({emp['employee_id']}) — {emp['role']}, {emp['department']}",
            f"Manager: {emp['manager_name']} | Security Tier: {emp['security_tier']} | Standing: {emp['standing']}",
            f"Compliance Result: {comp['status']} (Priority {comp['recommended_priority']})",
        ]
        if country:
            lines.append(
                f"Destination: {country} | Requested Duration: {req_days:g} days | "
                f"Rolling 12m Intl Used: {pto.get('international_remote_days_used_rolling_12m', 0)}/30 days"
            )
        if comp.get("violations"):
            lines.append("Violations: " + "; ".join(comp["violations"]))
        if comp.get("warnings"):
            lines.append("Conditions/Warnings: " + "; ".join(comp["warnings"]))
        lines.append("Policy Citations: " + ", ".join(comp.get("policy_citations", [])))
        lines.append("Note: Synthetic review draft prepared by Northstar HR Operations Agent.")
        return "\n".join(lines)

    @staticmethod
    def _format_employee_answer(
        emp: dict[str, Any],
        pto: dict[str, Any],
        benefits: dict[str, Any] | None,
        compliance: dict[str, Any] | None,
        show_holidays: bool,
        show_blackout: bool,
        has_draft: bool,
        has_ticket: bool,
    ) -> str:
        facts: list[str] = [
            f"**Employee Profile (`{emp['employee_id']}`):** {emp['name']}, {emp['role']} ({emp['department']}), "
            f"`{emp['employment_type']}`, Manager `{emp['manager_name']}`, Security Tier `{emp['security_tier']}`, "
            f"Probation Complete: `{emp['probation_complete']}` (`standing={emp['standing']}`)."
        ]
        if pto:
            facts.append(
                f"**PTO & Mobility Record:** `{pto.get('remaining_days')} days` remaining "
                f"(tier: {pto.get('accrual_tier')}), `{pto.get('floating_holidays_remaining')}` floating "
                f"holidays remaining, `{pto.get('international_remote_days_used_rolling_12m')}/30` rolling 12-month "
                f"international remote days used, `blackout_team_flag={pto.get('blackout_team_flag')}` (`[POL-001]`, `[POL-003]`)."
            )
        if benefits:
            if benefits.get("benefits_eligible"):
                facts.append(
                    f"**Benefits & Stipends (`[POL-006]`):** Plan `{benefits.get('plan_tier')}`, "
                    f"401(k) Match `{benefits.get('retirement_match_pct')}%`, Wellness Stipend remaining "
                    f"`${float(benefits.get('wellness_stipend_monthly_limit', 100)) - float(benefits.get('wellness_stipend_monthly_used', 0)):.0f}` "
                    f"this month (out of `$100`), L&D Budget remaining `${float(benefits.get('ld_budget_remaining', 0)):,.2f}`."
                )
            else:
                facts.append(
                    "**Benefits & Stipends (`[POL-012 | Section 2]`):** `benefits_eligible=false` — "
                    "1099 contractors are ineligible for health, 401(k), wellness, and L&D stipends."
                )
        if show_holidays:
            facts.append(
                "**Winter Recharge & Holiday Deductions:** December 26–31 is the paid Winter Recharge Shutdown "
                "and observed holidays do **not** consume personal PTO balances (`[POL-001 | Section 4.1]`, "
                "`[POL-002 | Section 4]`)."
            )
        if show_blackout:
            facts.append(
                "**Managed Coverage Blackout Rules:** Teams with `blackout_team_flag=true` or active release freezes "
                "require Department VP approval and an on-call swap for discretionary PTO > 2 consecutive days "
                "(`[POL-001 | Section 5.1]`)."
            )
        if compliance:
            cites = ", ".join(f"`[{c}]`" for c in compliance.get("policy_citations", []))
            facts.append(
                f"**Policy Compliance Verdict:** `{compliance.get('status')}` ({cites})."
            )
            for v in compliance.get("violations", []):
                facts.append(f"- **Policy Conflict:** {v}")
            for w in compliance.get("warnings", []):
                facts.append(f"- **Condition / Requirement:** {w}")

        next_steps: list[str] = []
        if compliance:
            approvers = compliance.get("required_approvers", [])
            if approvers:
                next_steps.append(
                    f"- **Required Sign-Offs (Priority {compliance.get('recommended_priority', 'P3')}):** "
                    + "; ".join(approvers) + "."
                )
        if has_draft:
            next_steps.append(
                "- **Approval/Escalation Email Drafted:** Review the generated draft in the Draft Email "
                "panel before sending manually."
            )
        if has_ticket:
            next_steps.append(
                "- **Mock HR Ticket Queued (Unconfirmed):** Click **Confirm & Create Mock HR Ticket** to "
                "persist the synthetic escalation record to `mock_data/tickets.json`."
            )
        if not next_steps:
            next_steps.append(
                "- Proceed with standard People Portal submission if desired, ensuring required manager advance notice is met."
            )

        return (
            "### Policy Facts (Cited)\n"
            + "\n".join(f"- {line}" if not line.startswith("- ") else line for line in facts)
            + "\n\n### Recommended Next Steps\n"
            + "\n".join(next_steps)
        )

    async def _run_policy_qa(
        self,
        user_query: str,
        mcp_client: MCPClientManager,
        trace: list[dict[str, Any]],
        citations_map: dict[str, dict[str, Any]],
        state: dict[str, Any],
    ) -> AgentTurnResult:
        search_res = await self._exec(
            mcp_client,
            "search_policy_documents",
            {"query": user_query, "top_k": 5},
            trace,
            citations_map,
            state,
        )
        m_doc = re.search(r"\b(POL-\d{3})\b", user_query, re.I)
        if m_doc:
            await self._exec(
                mcp_client,
                "get_policy_section",
                {"doc_id": m_doc.group(1).upper(), "section_query": ""},
                trace,
                citations_map,
                state,
            )

        below = bool(search_res.get("below_threshold", False))
        hits = search_res.get("hits", [])
        if below and not m_doc:
            return AgentTurnResult(
                answer=(
                    "### Policy Facts (Cited)\n"
                    "- No matching Northstar Cloud Labs HR policy was found above the relevance threshold "
                    "for this query.\n\n"
                    "### Recommended Next Steps\n"
                    "- This question appears to fall **outside Northstar's indexed HR policy corpus** "
                    "(covering PTO, holidays, remote/international work, expenses, security, benefits, "
                    "onboarding, equipment, medical/parental leave, workplace conduct, and contractors). "
                    "If this is a specialized HR inquiry, escalate directly to `people-ops@northstarcloud.example`."
                ),
                mode_used="mock",
                trace=trace,
                citations=[],
                abstained=True,
            )

        fact_bullets: list[str] = []
        filtered_hits = [
            h
            for i, h in enumerate(hits)
            if i == 0 or float(h.get("bm25_score", 0.0)) >= 5.0
        ]
        # Keep only filtered hits in citations map for clean precision
        kept_ids = {h.get("chunk_id") for h in filtered_hits[:4]}
        for cid in list(citations_map.keys()):
            if cid not in kept_ids:
                del citations_map[cid]

        seen_keys: set[str] = set()
        for hit in filtered_hits[:4]:
            key = f"{hit['doc_id']}:{hit['section_path']}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            full_clean = " ".join(hit.get("text", hit.get("snippet", "")).split())
            excerpt = full_clean if len(full_clean) <= 680 else hit.get("snippet", full_clean[:680])
            if len(full_clean) > 680 and excerpt != full_clean:
                excerpt = f"{hit.get('snippet', '')} ... {full_clean[:420]}" if len(hit.get("snippet", "")) < 260 else full_clean[:680]
            fact_bullets.append(
                f"- **[{hit['doc_id']} | {hit['section_path']} ({hit['page_or_anchor']})]:** {excerpt}"
            )

        top_doc = filtered_hits[0]["doc_id"] if filtered_hits else "POL-001"
        answer = (
            "### Policy Facts (Cited)\n"
            + "\n".join(fact_bullets)
            + "\n\n### Recommended Next Steps\n"
            + f"- Apply the requirements above per `{top_doc}` (see the **Citations & Snippets** panel for "
              "verbatim policy text). Provide an employee ID (e.g., `EMP-1042`, `EMP-1018`, `EMP-1055`) if you "
              "would like an automated compliance evaluation or approval draft."
        )
        return AgentTurnResult(
            answer=answer,
            mode_used="mock",
            trace=trace,
            citations=list(citations_map.values()),
            abstained=False,
        )
