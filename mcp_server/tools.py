"""8 Northstar HR & Policy tools exposed exclusively through the MCP server."""

from __future__ import annotations

from functools import lru_cache
import threading
from typing import Any

from agent.compliance import MockHRDataStore, evaluate_policy_compliance
from app_config import get_settings
from rag.retriever import HybridPolicyRetriever

_RETRIEVER_LOCK = threading.Lock()
_CACHED_RETRIEVER: HybridPolicyRetriever | None = None
_CACHED_MANIFEST_MTIME: int = -1


def _get_retriever() -> HybridPolicyRetriever:
    global _CACHED_RETRIEVER, _CACHED_MANIFEST_MTIME
    settings = get_settings()
    manifest_path = settings.rag_index_dir / "manifest.json"
    with _RETRIEVER_LOCK:
        mtime = manifest_path.stat().st_mtime_ns if manifest_path.exists() else -1
        if _CACHED_RETRIEVER is None or (mtime != -1 and mtime != _CACHED_MANIFEST_MTIME):
            _CACHED_RETRIEVER = HybridPolicyRetriever(settings)
            _CACHED_MANIFEST_MTIME = (
                manifest_path.stat().st_mtime_ns if manifest_path.exists() else -1
            )
        return _CACHED_RETRIEVER


@lru_cache(maxsize=1)
def _get_store() -> MockHRDataStore:
    return MockHRDataStore(get_settings())


def search_policy_documents(
    query: str,
    top_k: int = 5,
    category: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    """Hybrid Dense+BM25+RRF search over Northstar HR policy documents with optional category/doc_id filter."""
    res = _get_retriever().search(
        query=query,
        top_k=max(1, min(int(top_k), 12)),
        category=category,
        doc_id=doc_id,
    )
    return res.to_dict()


def get_policy_section(doc_id: str, section_query: str = "") -> dict[str, Any]:
    """Retrieve exact full policy section text and page/anchor metadata for a Document ID (e.g., POL-003)."""
    chunks = _get_retriever().get_section(doc_id=doc_id, section_query=section_query)
    if not chunks:
        return {
            "found": False,
            "doc_id": doc_id.upper(),
            "sections": [],
            "error": f"Document '{doc_id}' was not found in the indexed corpus.",
        }
    return {
        "found": True,
        "doc_id": chunks[0].doc_id,
        "doc_title": chunks[0].doc_title,
        "source_file": chunks[0].source_file,
        "sections": [
            {
                "chunk_id": c.chunk_id,
                "section_path": c.section_path,
                "page_or_anchor": c.page_or_anchor,
                "text": c.text,
            }
            for c in chunks
        ],
    }


def lookup_employee_profile(employee_id: str) -> dict[str, Any]:
    """Look up a synthetic employee's profile, role, manager, security tier, and probation standing."""
    emp = _get_store().get_employee(employee_id)
    if emp is None:
        return {
            "found": False,
            "employee_id": employee_id,
            "error": f"Employee ID '{employee_id}' does not exist in HR records.",
        }
    return {"found": True, "employee": emp}


def check_pto_balance(employee_id: str) -> dict[str, Any]:
    """Retrieve a synthetic employee's PTO balance, accruals, floating holidays, and rolling 12-month remote days."""
    store = _get_store()
    emp = store.get_employee(employee_id)
    bal = store.get_pto_balance(employee_id)
    if emp is None or bal is None:
        return {
            "found": False,
            "employee_id": employee_id,
            "error": f"PTO record for '{employee_id}' was not found.",
        }
    return {
        "found": True,
        "employee_id": emp["employee_id"],
        "employee_name": emp["name"],
        "pto_balance": bal,
    }


def lookup_benefits_status(employee_id: str) -> dict[str, Any]:
    """Retrieve a synthetic employee's health plan, 401(k) match, wellness stipend, and L&D budget remaining."""
    store = _get_store()
    emp = store.get_employee(employee_id)
    ben = store.get_benefits_status(employee_id)
    if emp is None or ben is None:
        return {
            "found": False,
            "employee_id": employee_id,
            "error": f"Benefits record for '{employee_id}' was not found.",
        }
    return {
        "found": True,
        "employee_id": emp["employee_id"],
        "employee_name": emp["name"],
        "benefits": ben,
    }


def check_policy_compliance(
    employee_id: str,
    request_type: str,
    days_requested: float = 0.0,
    destination_country: str = "",
    advance_notice_days: int | None = None,
    during_blackout: bool = False,
    amount_usd: float = 0.0,
) -> dict[str, Any]:
    """Evaluate structured employee eligibility, quantitative caps, blackout windows, and InfoSec compliance."""
    return evaluate_policy_compliance(
        store=_get_store(),
        employee_id=employee_id,
        request_type=request_type,
        days_requested=days_requested,
        destination_country=destination_country,
        advance_notice_days=advance_notice_days,
        during_blackout=during_blackout,
        amount_usd=amount_usd,
    )


def draft_hr_email(
    recipient: str,
    subject: str,
    body: str,
    cc_list: list[str] | None = None,
) -> dict[str, Any]:
    """Compose a review-ready HR approval or escalation email draft (never dispatches external emails)."""
    clean_cc = [c.strip() for c in (cc_list or []) if c.strip()]
    return {
        "status": "DRAFT_ONLY",
        "sent": False,
        "is_mock": True,
        "draft": {
            "to": recipient.strip(),
            "cc": clean_cc,
            "subject": subject.strip(),
            "body": body.strip(),
        },
        "note": "Review-only draft generated. No external email was transmitted.",
    }


def create_mock_hr_ticket(
    employee_id: str,
    category: str,
    priority: str,
    summary: str,
    policy_references: list[str] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Preview (confirmed=False) or persist (confirmed=True) a synthetic mock HR escalation ticket."""
    norm_prio = priority.strip().upper()
    if norm_prio not in {"P1", "P2", "P3"}:
        norm_prio = "P2"
    return _get_store().create_mock_ticket(
        employee_id=employee_id,
        category=category,
        priority=norm_prio,  # type: ignore[arg-type]
        summary=summary,
        policy_references=policy_references,
        confirmed=bool(confirmed),
    )
