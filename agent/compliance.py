"""Deterministic HR policy compliance evaluator and mock data store access."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal

from app_config import Settings, get_settings

APPROVED_INTL_COUNTRIES = frozenset(
    {
        "portugal",
        "spain",
        "france",
        "germany",
        "netherlands",
        "ireland",
        "italy",
        "united kingdom",
        "uk",
        "canada",
        "united states",
        "us",
        "usa",
        "costa rica",
        "mexico",
        "japan",
        "australia",
    }
)

PROHIBITED_COUNTRIES = frozenset(
    {
        "russia",
        "belarus",
        "iran",
        "north korea",
        "syria",
        "cuba",
        "china",
        "mainland china",
    }
)


class MockHRDataStore:
    """Thread-safe JSON loader and synthetic ticket writer for `mock_data/`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.data_dir: Path = self.settings.mock_data_dir

    def _read_json(self, filename: str) -> dict[str, Any]:
        return json.loads((self.data_dir / filename).read_text(encoding="utf-8"))

    def get_employee(self, employee_id: str) -> dict[str, Any] | None:
        norm = employee_id.strip().upper()
        for emp in self._read_json("employees.json").get("employees", []):
            if emp.get("employee_id", "").upper() == norm:
                return emp
        return None

    def get_pto_balance(self, employee_id: str) -> dict[str, Any] | None:
        norm = employee_id.strip().upper()
        return self._read_json("pto_balances.json").get("balances", {}).get(norm)

    def get_benefits_status(self, employee_id: str) -> dict[str, Any] | None:
        norm = employee_id.strip().upper()
        return self._read_json("benefits.json").get("benefits", {}).get(norm)

    def list_tickets(self) -> list[dict[str, Any]]:
        return self._read_json("tickets.json").get("tickets", [])

    def create_mock_ticket(
        self,
        employee_id: str,
        category: str,
        priority: Literal["P1", "P2", "P3"],
        summary: str,
        policy_references: list[str] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Preview or persist a synthetic HR escalation ticket (`is_mock: true`)."""
        norm_id = employee_id.strip().upper()
        clean_refs = [r.strip().upper() for r in (policy_references or []) if r.strip()]
        if not confirmed:
            return {
                "persisted": False,
                "status": "PENDING_CONFIRMATION",
                "requires_confirmation": True,
                "is_mock": True,
                "proposed_ticket": {
                    "employee_id": norm_id,
                    "category": category,
                    "priority": priority,
                    "summary": summary,
                    "policy_references": clean_refs,
                    "is_mock": True,
                },
                "message": (
                    "Preview only: user confirmation is required before persisting "
                    "this mock HR ticket."
                ),
            }

        tickets_path = self.data_dir / "tickets.json"
        payload = json.loads(tickets_path.read_text(encoding="utf-8"))
        tickets: list[dict[str, Any]] = payload.get("tickets", [])
        next_num = 1001 + len(tickets)
        existing_ids = {t.get("ticket_id") for t in tickets}
        while f"HR-{next_num}" in existing_ids:
            next_num += 1

        record = {
            "ticket_id": f"HR-{next_num}",
            "employee_id": norm_id,
            "category": category,
            "priority": priority,
            "summary": summary,
            "status": "OPEN_PENDING_REVIEW",
            "policy_references": clean_refs,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_mock": True,
        }
        tickets.append(record)
        payload["tickets"] = tickets
        tickets_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {
            "persisted": True,
            "status": "CREATED",
            "requires_confirmation": False,
            "is_mock": True,
            "ticket": record,
        }


def _evaluate_international_work(
    emp: dict[str, Any],
    pto: dict[str, Any],
    days_requested: float,
    destination_country: str,
    advance_notice_days: int | None,
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []
    approvers = [
        f"Direct Manager ({emp.get('manager_name', 'Manager')}) — 4h overlap verification",
        "People Operations & Global Mobility",
        "Information Security (InfoSec)",
    ]
    citations = ["POL-003 Sec 3", "POL-005 Sec 4"]
    priority: Literal["P1", "P2", "P3"] = "P3"

    if emp.get("employment_type") != "FTE":
        violations.append(
            "Only Full-Time Regular Employees (FTEs) are eligible for temporary "
            "international remote work (POL-003 Sec 3; POL-012 Sec 3.1)."
        )
        citations.append("POL-012 Sec 3.1")

    if not emp.get("probation_complete", False):
        violations.append(
            "Employees in their first 90-day probation period are ineligible for "
            "temporary international remote work (POL-003 Sec 2.3; POL-007 Sec 3.1)."
        )
        citations.append("POL-007 Sec 3.1")

    country_norm = destination_country.strip().lower()
    if not country_norm:
        warnings.append("Destination country was not specified; jurisdiction check pending.")
    elif country_norm in PROHIBITED_COUNTRIES:
        violations.append(
            f"'{destination_country}' is a sanctions-restricted or prohibited jurisdiction; "
            "company laptops and network access are prohibited (POL-003 Sec 3.2; POL-005 Sec 4.2)."
        )
        priority = "P2"
    elif country_norm not in APPROVED_INTL_COUNTRIES:
        warnings.append(
            f"'{destination_country}' is outside pre-approved low-tax-nexus jurisdictions "
            "and requires Global Mobility, Tax & Legal review (POL-003 Sec 3.2)."
        )
        approvers.extend(["Department VP", "Legal & Tax Counsel"])
        priority = "P2"

    used_rolling = int(pto.get("international_remote_days_used_rolling_12m", 0))
    projected_total = used_rolling + days_requested
    remaining_cap = max(0, 30 - used_rolling)
    if projected_total > 30:
        violations.append(
            f"Requested {days_requested:g} calendar days plus {used_rolling} rolling "
            f"days used equals {projected_total:g} days, exceeding the 30-day rolling "
            f"12-month cap (remaining standard allowance: {remaining_cap} days) (POL-003 Sec 3.1)."
        )
        approvers.extend(["Department VP", "Global Mobility, Tax & Legal Counsel"])
        citations.append("POL-011 Sec 2.2")
        priority = "P2"

    if advance_notice_days is not None and advance_notice_days < 15:
        warnings.append(
            f"Submitted {advance_notice_days} business days ahead; POL-003 Sec 3.3 requires "
            "at least 15 business days advance notice."
        )

    sec_tier = emp.get("security_tier", "Standard-Corp")
    if sec_tier in {"Prod-Admin", "Customer-PII"}:
        warnings.append(
            f"Employee security tier is '{sec_tier}': InfoSec-issued Clean Travel Loaner "
            "Laptop is mandatory; primary production workstation cannot cross borders "
            "(POL-003 Sec 4; POL-005 Sec 4.1)."
        )
        if priority == "P3":
            priority = "P2"
    else:
        warnings.append(
            f"Security tier '{sec_tier}' permits primary corporate laptop with full-disk "
            "encryption, WireGuard VPN, and hardware FIDO2 MFA (POL-003 Sec 4; POL-005 Sec 3)."
        )

    return {
        "eligible": len(violations) == 0,
        "status": "NON_COMPLIANT" if violations else "CONDITIONAL_APPROVAL",
        "violations": violations,
        "warnings": warnings,
        "required_approvers": list(dict.fromkeys(approvers)),
        "recommended_priority": priority,
        "policy_citations": list(dict.fromkeys(citations)),
        "metrics": {
            "rolling_12m_used_days": used_rolling,
            "requested_days": days_requested,
            "projected_rolling_total": projected_total,
            "remaining_30_day_allowance": remaining_cap,
            "security_tier": sec_tier,
            "requires_loaner_laptop": sec_tier in {"Prod-Admin", "Customer-PII"},
        },
    }


def _evaluate_pto_request(
    emp: dict[str, Any],
    pto: dict[str, Any],
    days_requested: float,
    advance_notice_days: int | None,
    during_blackout: bool,
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []
    approvers = [f"Direct Manager ({emp.get('manager_name', 'Manager')})"]
    citations = ["POL-001 Sec 3", "POL-001 Sec 4"]
    priority: Literal["P1", "P2", "P3"] = "P3"

    if not pto.get("eligible_for_pto", False) or emp.get("employment_type") == "Contractor":
        violations.append(
            "1099 Independent Contractors and fixed-term interns do not accrue or take "
            "paid PTO (POL-001 Sec 2.2; POL-012 Sec 2)."
        )
        return {
            "eligible": False,
            "status": "NON_COMPLIANT",
            "violations": violations,
            "warnings": warnings,
            "required_approvers": ["Hiring Manager (unpaid schedule coordination only)"],
            "recommended_priority": "P3",
            "policy_citations": ["POL-001 Sec 2.2", "POL-012 Sec 2"],
            "metrics": {"remaining_pto_days": float(pto.get("remaining_days", 0.0))},
        }

    remaining = float(pto.get("remaining_days", 0.0))
    projected_balance = round(remaining - days_requested, 2)
    on_probation = not emp.get("probation_complete", False)

    if on_probation and days_requested > 2:
        violations.append(
            f"Employee is on 90-day probation ({emp.get('tenure_days')} days tenure); "
            "requests of 3+ consecutive PTO days require People Ops & Manager exception approval "
            "(POL-001 Sec 5.2; POL-007 Sec 3.2)."
        )
        approvers.append("People Operations")
        citations.extend(["POL-001 Sec 5.2", "POL-007 Sec 3.2"])
        priority = "P2"

    if projected_balance < 0:
        deficit = abs(projected_balance)
        if on_probation:
            violations.append(
                f"Projected balance ({projected_balance:g} days) is negative; probationary "
                "employees cannot carry a negative PTO balance (POL-001 Sec 3.1)."
            )
            priority = "P2"
        elif deficit <= 2.0:
            warnings.append(
                f"Request creates a {deficit:g}-day negative PTO balance (within the 2.0-day "
                "borrowing limit); requires written Manager and People Ops approval (POL-001 Sec 3.1)."
            )
            approvers.append("People Operations")
            priority = "P2"
        else:
            violations.append(
                f"Projected deficit of {deficit:g} days exceeds the maximum 2.0-day negative "
                "PTO borrowing limit (POL-001 Sec 3.1; POL-011 Sec 2.2)."
            )
            approvers.extend(["People Operations", "Department VP"])
            citations.append("POL-011 Sec 2.2")
            priority = "P2"

    if days_requested >= 10:
        approvers.append("Department VP")
        required_notice = 20
    elif days_requested >= 3:
        warnings.append("Requires documented handoff plan with designated backup POC (POL-001 Sec 4).")
        required_notice = 10
    else:
        required_notice = 5

    if advance_notice_days is not None and advance_notice_days < required_notice:
        warnings.append(
            f"Advance notice of {advance_notice_days} business days is below the {required_notice}-day "
            "requirement for a {days_requested:g}-day PTO request (POL-001 Sec 4)."
        )

    if during_blackout or (pto.get("blackout_team_flag") and days_requested > 2):
        warnings.append(
            "Employee/window involves a Managed Coverage Blackout period; PTO > 2 consecutive "
            "days requires Department VP approval and verified on-call swap (POL-001 Sec 5.1)."
        )
        approvers.append("Department VP (On-Call Swap Verification)")
        citations.append("POL-001 Sec 5.1")
        priority = "P2"

    return {
        "eligible": len(violations) == 0,
        "status": "NON_COMPLIANT" if violations else ("CONDITIONAL_APPROVAL" if warnings else "COMPLIANT"),
        "violations": violations,
        "warnings": warnings,
        "required_approvers": list(dict.fromkeys(approvers)),
        "recommended_priority": priority,
        "policy_citations": list(dict.fromkeys(citations)),
        "metrics": {
            "remaining_pto_days": remaining,
            "requested_days": days_requested,
            "projected_balance_after_request": projected_balance,
            "floating_holidays_remaining": int(pto.get("floating_holidays_remaining", 0)),
        },
    }


def _evaluate_expense_or_ld(
    emp: dict[str, Any],
    benefits: dict[str, Any] | None,
    amount_usd: float,
    during_blackout: bool,
) -> dict[str, Any]:
    citations = ["POL-004 Sec 2", "POL-006 Sec 6"]
    warnings: list[str] = []
    violations: list[str] = []
    approvers = [f"Direct Manager ({emp.get('manager_name', 'Manager')})"]
    priority: Literal["P1", "P2", "P3"] = "P3"

    if emp.get("employment_type") == "Contractor":
        violations.append(
            "1099 Independent Contractors are ineligible for L&D, wellness, and home office "
            "employee stipends (POL-012 Sec 2; POL-012 Sec 3.1)."
        )
        return {
            "eligible": False,
            "status": "NON_COMPLIANT",
            "violations": violations,
            "warnings": warnings,
            "required_approvers": [],
            "recommended_priority": "P3",
            "policy_citations": ["POL-012 Sec 2", "POL-012 Sec 3.1"],
            "metrics": {"requested_amount_usd": amount_usd},
        }

    if benefits is not None:
        ld_rem = float(benefits.get("ld_budget_remaining", 0.0))
        if amount_usd > ld_rem:
            violations.append(
                f"Requested ${amount_usd:,.2f} exceeds remaining annual L&D budget "
                f"(${ld_rem:,.2f}) (POL-006 Sec 6)."
            )
            approvers.extend(["People Operations", "Department VP"])
            priority = "P2"
        elif amount_usd > 500 or during_blackout:
            warnings.append(
                "Exceptions or single reimbursement splits above $500 require documented "
                "manager pre-approval and itemized receipts within 30 days (POL-004; POL-011 Sec 2.2)."
            )
            approvers.append("People Operations")
            priority = "P2"
    return {
        "eligible": len(violations) == 0,
        "status": "NON_COMPLIANT" if violations else ("CONDITIONAL_APPROVAL" if warnings else "COMPLIANT"),
        "violations": violations,
        "warnings": warnings,
        "required_approvers": list(dict.fromkeys(approvers)),
        "recommended_priority": priority,
        "policy_citations": citations,
        "metrics": {
            "requested_amount_usd": amount_usd,
            "ld_budget_remaining": float(benefits.get("ld_budget_remaining", 0.0)) if benefits else 0.0,
        },
    }


def evaluate_policy_compliance(
    store: MockHRDataStore,
    employee_id: str,
    request_type: str,
    days_requested: float = 0.0,
    destination_country: str = "",
    advance_notice_days: int | None = None,
    during_blackout: bool = False,
    amount_usd: float = 0.0,
) -> dict[str, Any]:
    """Run deterministic policy compliance checks against employee records and rules."""
    emp = store.get_employee(employee_id)
    if emp is None:
        return {
            "found": False,
            "error": f"Employee ID '{employee_id}' was not found in HR records.",
        }
    pto = store.get_pto_balance(employee_id) or {}
    benefits = store.get_benefits_status(employee_id)
    req = request_type.strip().lower()

    if req in {"international_remote_work", "workcation", "international"}:
        result = _evaluate_international_work(
            emp, pto, days_requested, destination_country, advance_notice_days
        )
    elif req in {"pto", "pto_request", "vacation", "leave"}:
        result = _evaluate_pto_request(
            emp, pto, days_requested, advance_notice_days, during_blackout
        )
    elif req in {"expense", "ld", "reimbursement", "expense_or_ld"}:
        result = _evaluate_expense_or_ld(emp, benefits, amount_usd, during_blackout)
    elif req in {"ethics", "harassment", "retaliation", "p1_escalation", "ethics_escalation"}:
        result = {
            "eligible": False,
            "status": "ESCALATION_REQUIRED",
            "violations": [],
            "warnings": [
                "Report triggers Priority P1 Confidential People Operations & Ethics Queue "
                "(4-business-hour SLA). Never CC direct manager when manager is implicated "
                "(POL-010 Sec 4; POL-011 Sec 2.1)."
            ],
            "required_approvers": ["Confidential People Operations & Ethics Queue (ethics@northstarcloud.example)"],
            "recommended_priority": "P1",
            "policy_citations": ["POL-010 Sec 4", "POL-011 Sec 2.1"],
            "metrics": {},
        }
    else:
        return {
            "found": True,
            "error": (
                f"Unsupported request_type '{request_type}'. Supported types: "
                "pto_request, international_remote_work, expense_or_ld, ethics_escalation."
            ),
        }

    return {
        "found": True,
        "employee_id": emp["employee_id"],
        "employee_name": emp["name"],
        "role": emp["role"],
        "department": emp["department"],
        "request_type": req,
        **result,
    }
