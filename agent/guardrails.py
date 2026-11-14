"""Input/output guardrails, prompt injection defense, ambiguity checks, and safety gates."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

_INJECTION_PATTERNS = (
    re.compile(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|policies|rules|guidelines)",
        re.I,
    ),
    re.compile(r"reveal\s+(?:your\s+)?(?:system\s+prompt|api\s*key|secret)", re.I),
    re.compile(r"(?:print|show|dump)\s+(?:env|environment\s+variables|\.env)", re.I),
    re.compile(r"bypass\s+(?:infosec|policy|guardrail|approval|confirmation)", re.I),
    re.compile(r"confirmed\s*=\s*true", re.I),
    re.compile(r"skip\s+(?:user\s+)?confirmation", re.I),
    re.compile(r"immediately\s+submit\s+an?\s+approved\s+(?:hr\s+)?ticket", re.I),
    re.compile(r"you\s+are\s+now\s+(?:dan|unrestricted|root)", re.I),
)

_ETHICS_P1_RE = re.compile(
    r"\b(?:harass\w*|retaliat\w*|discriminat\w*|hostile\s+work|whistleblow\w*|assault|unsafe)\b",
    re.I,
)

_EMP_ID_RE = re.compile(r"\b(EMP-\d{3,5})\b", re.I)

KNOWN_EMPLOYEE_ALIASES: dict[str, str] = {
    "elena rostova": "EMP-1001",
    "marcus vance": "EMP-1002",
    "priya nair": "EMP-1003",
    "carlos vega": "EMP-1018",
    "maya lin": "EMP-1042",
    "liam o'connor": "EMP-1055",
    "liam oconnor": "EMP-1055",
    "sofia chen": "EMP-1071",
    "jordan brooks": "EMP-1089",
}

_PERSONAL_PRONOUN_REQUEST_RE = re.compile(
    r"\b(?:my|i|am\s+i|check\s+(?:his|her|their|the\s+employee'?s))\b", re.I
)
_PERSONAL_RECORD_TOPICS_RE = re.compile(
    r"(?:"
    r"\bpto\s+balance\b|"
    r"\bremaining\s+(?:pto|days|budget|balance)\b|"
    r"\btake\s+(?:off|leave)\s+next\b|"
    r"\bhome\s+office\s+stipend\b|"
    r"\bexpense\s+this\s+equipment\b|"
    r"\bwork\s+remotely\s+next\b|"
    r"\bcan\s+i\s+(?:take|work|expense|borrow|request)\b|"
    r"\bam\s+i\s+eligible\b|"
    r"\bstipend\s+remaining\b|"
    r"\bl&d\s+balance\b"
    r")",
    re.I,
)

_OUT_OF_SCOPE_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\b(?:what|which)\s+stocks?\b|\bstock\s+picks?\b|\binvestment\s+advice\b", re.I),
        "out_of_scope_financial_advice",
        (
            "### Policy Facts (Cited)\n"
            "- Northstar offers a **4% dollar-for-dollar 401(k) employer match** (`[POL-006 | Section 4.1]`), "
            "but company HR policies do **not** provide personal investment or stock-selection advice.\n\n"
            "### Recommended Next Steps\n"
            "- Consult your 401(k) plan fiduciary portal or a licensed financial advisor for fund allocation guidance."
        ),
    ),
    (
        re.compile(r"\bcalculate\s+(?:my\s+)?(?:personal\s+)?.*tax\b|\btax\s+liability\b|\btax\s+return\b", re.I),
        "out_of_scope_tax_legal_advice",
        (
            "### Policy Facts (Cited)\n"
            "- Northstar does **not** calculate personal domestic or foreign income tax liability or give "
            "personal tax/legal advice (`[POL-003 | Section 1]`).\n\n"
            "### Recommended Next Steps\n"
            "- For corporate permanent-establishment/mobility thresholds (`30 rolling days`), consult "
            "Global Mobility (`mobility@northstarcloud.example`); for personal tax liability, consult a qualified CPA."
        ),
    ),
    (
        re.compile(r"\b(?:pets?|dogs?|cats?|tokyo\s+office|seoul\s+office)\b", re.I),
        "out_of_corpus_topic",
        (
            "### Policy Facts (Cited)\n"
            "- Northstar's indexed HR policy corpus covers regional hubs in **New York, Austin, Toronto, and London** "
            "(`[POL-003 | Section 1]`) and does **not** contain a Tokyo office directory or workplace pet policy.\n\n"
            "### Recommended Next Steps\n"
            "- Because this topic is absent from Northstar's HR policy documents, please escalate to "
            "`people-ops@northstarcloud.example` rather than assuming coverage."
        ),
    ),
)


@dataclass(slots=True)
class InputGuardrailOutcome:
    """Result of evaluating user input before calling MCP tools."""

    blocked: bool = False
    clarification_needed: bool = False
    out_of_scope: bool = False
    reason: str = ""
    safe_message: str = ""
    resolved_employee_id: str | None = None
    is_p1_ethics: bool = False
    flags: list[str] = field(default_factory=list)


def resolve_employee_id(text: str) -> str | None:
    """Extract explicit `EMP-XXXX` ID or match a known synthetic persona name."""
    m = _EMP_ID_RE.search(text)
    if m:
        return m.group(1).upper()
    lower = text.lower()
    for name, emp_id in KNOWN_EMPLOYEE_ALIASES.items():
        if name in lower:
            return emp_id
    return None


def check_input_guardrails(user_query: str) -> InputGuardrailOutcome:
    """Validate user input for prompt injection, missing context, out-of-scope advice, and P1 sensitivity."""
    text = (user_query or "").strip()
    if not text:
        return InputGuardrailOutcome(
            clarification_needed=True,
            reason="empty_query",
            safe_message=(
                "Please enter an HR policy question or employee workflow request "
                "(e.g., ask about PTO accruals, 401(k) match, or specify an employee ID such as EMP-1042)."
            ),
            flags=["empty_query"],
        )

    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return InputGuardrailOutcome(
                blocked=True,
                reason="prompt_injection_detected",
                safe_message=(
                    "I cannot comply with requests to ignore policy guardrails, reveal internal "
                    "system instructions/credentials, or bypass mandatory confirmation and approval workflows."
                ),
                flags=["prompt_injection_blocked"],
            )

    for pat, reason, msg in _OUT_OF_SCOPE_PATTERNS:
        if pat.search(text):
            return InputGuardrailOutcome(
                out_of_scope=True,
                reason=reason,
                safe_message=msg,
                flags=[reason],
            )

    emp_id = resolve_employee_id(text)
    is_p1 = bool(_ETHICS_P1_RE.search(text))

    # Ambiguous personal-balance or eligibility query missing an employee identifier
    if (
        emp_id is None
        and _PERSONAL_PRONOUN_REQUEST_RE.search(text)
        and _PERSONAL_RECORD_TOPICS_RE.search(text)
        and not is_p1
    ):
        return InputGuardrailOutcome(
            clarification_needed=True,
            reason="missing_employee_id",
            safe_message=(
                "### Clarification Needed\n"
                "- To evaluate individual eligibility, PTO balances, equipment/home-office reimbursement, "
                "or domestic vs. international remote work rules, please specify:\n"
                "  1. **Employee ID or Name** (e.g., `EMP-1042` Maya Lin, `EMP-1018` Carlos Vega, "
                "`EMP-1055` Liam O'Connor, `EMP-1071` Sofia Chen, or `EMP-1089` Jordan Brooks).\n"
                "  2. Relevant specifics such as **exact dates/duration, item & USD cost, or destination country**."
            ),
            flags=["missing_employee_id"],
        )

    flags: list[str] = []
    if is_p1:
        flags.append("p1_confidential_ethics")
    return InputGuardrailOutcome(
        blocked=False,
        clarification_needed=False,
        resolved_employee_id=emp_id,
        is_p1_ethics=is_p1,
        flags=flags,
    )


def sanitize_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Enforce execution safety invariants before invoking MCP tools from an agent turn."""
    clean = dict(arguments or {})
    if tool_name == "create_mock_hr_ticket":
        clean["confirmed"] = False
    return clean


def summarize_tool_output(tool_name: str, payload: dict[str, Any]) -> str:
    """Create a concise, thought-free operational trace summary for UI & audit logs."""
    if not payload or payload.get("error"):
        return f"Error: {payload.get('error', 'Unknown error')}"
    if tool_name == "search_policy_documents":
        hits = payload.get("hits", [])
        docs = ", ".join(dict.fromkeys(h.get("doc_id", "?") for h in hits[:4]))
        return f"Retrieved {len(hits)} chunks ({docs or 'none'}); below_threshold={payload.get('below_threshold')}"
    if tool_name == "get_policy_section":
        secs = payload.get("sections", [])
        return f"Loaded {len(secs)} section(s) from {payload.get('doc_id', '?')}"
    if tool_name == "lookup_employee_profile":
        emp = payload.get("employee", {})
        return (
            f"{emp.get('employee_id')} {emp.get('name')} | {emp.get('employment_type')} | "
            f"{emp.get('security_tier')} | standing={emp.get('standing')}"
        )
    if tool_name == "check_pto_balance":
        bal = payload.get("pto_balance", {})
        return (
            f"remaining={bal.get('remaining_days')}d, floating={bal.get('floating_holidays_remaining')}, "
            f"intl_used_12m={bal.get('international_remote_days_used_rolling_12m')}d"
        )
    if tool_name == "lookup_benefits_status":
        ben = payload.get("benefits", {})
        return (
            f"eligible={ben.get('benefits_eligible')}, plan={ben.get('plan_tier')}, "
            f"ld_remaining=${ben.get('ld_budget_remaining')}"
        )
    if tool_name == "check_policy_compliance":
        return (
            f"status={payload.get('status')}, priority={payload.get('recommended_priority')}, "
            f"violations={len(payload.get('violations', []))}, warnings={len(payload.get('warnings', []))}"
        )
    if tool_name == "draft_hr_email":
        draft = payload.get("draft", {})
        return f"Draft email to {draft.get('to')} | Subject: {draft.get('subject')}"
    if tool_name == "create_mock_hr_ticket":
        if payload.get("persisted"):
            t = payload.get("ticket", {})
            return f"Persisted mock ticket {t.get('ticket_id')} ({t.get('priority')})"
        prop = payload.get("proposed_ticket", {})
        return f"Previewed mock ticket ({prop.get('priority')}, awaiting confirmation)"
    return "Completed"
