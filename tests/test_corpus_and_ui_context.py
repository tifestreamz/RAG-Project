"""Verification tests for /corpus routes and structured ui_context metadata."""

from fastapi.testclient import TestClient

from web.app import app


def test_chat_returns_structured_ui_context_for_compliance_queries() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/chat",
            json={
                "message": "Can Maya Lin (EMP-1042) take a 6-week remote workcation from Lisbon, Portugal?",
                "provider_override": "mock",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ui_context" in data
        ui_ctx = data["ui_context"]
        assert ui_ctx["employee"]["employee_id"] == "EMP-1042"
        assert ui_ctx["compliance"]["request_type"] == "international_remote_work"
        assert ui_ctx["compliance"]["metrics"]["rolling_12m_used_days"] == 5
        assert ui_ctx["compliance"]["metrics"]["requested_days"] == 42
        assert ui_ctx["compliance"]["metrics"]["projected_rolling_total"] == 47

        step1 = client.post(
            "/chat",
            json={
                "message": "Can contractor Jordan Brooks (EMP-1089) claim a $500 home office ergonomic chair stipend?",
                "provider_override": "mock",
            },
        )
        assert step1.status_code == 200
        d1 = step1.json()
        assert d1["ui_context"]["employee"]["employee_id"] == "EMP-1089"

        step2 = client.post(
            "/chat",
            json={
                "message": "Prepare a mock HR ticket preview for this request.",
                "provider_override": "mock",
                "context": {
                    "previous_query": "Can contractor Jordan Brooks (EMP-1089) claim a $500 home office ergonomic chair stipend?",
                    "employee_id": "EMP-1089",
                    "employee_name": "Jordan Brooks",
                    "policy_doc_ids": ["POL-012", "POL-004"],
                },
            },
        )
        assert step2.status_code == 200
        d2 = step2.json()
        assert d2["pending_confirmation"] is not None
        assert d2["pending_confirmation"]["employee_id"] == "EMP-1089"


def test_corpus_endpoints_format_all_twelve_documents() -> None:
    with TestClient(app) as client:
        page = client.get("/corpus")
        assert page.status_code == 200

        listing = client.get("/api/corpus")
        assert listing.status_code == 200
        docs = listing.json().get("documents", [])
        assert len(docs) == 12

        for idx in range(1, 13):
            doc_id = f"POL-{idx:03d}"
            resp = client.get(f"/api/corpus/{doc_id}")
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["doc_id"] == doc_id
            assert payload["sections"], f"{doc_id} missing readable sections"
            assert payload["chunks"], f"{doc_id} missing indexed chunks"

        # HTML tables should arrive as Markdown pipe tables for rich UI rendering
        pol008 = client.get("/api/corpus/POL-008").json()
        assert any("| :---" in sec["text"] for sec in pol008["sections"])

        # PDF page footers should be stripped from readable Document view
        pol005 = client.get("/api/corpus/POL-005").json()
        assert all("POL-005 - Page" not in sec["text"] for sec in pol005["sections"])
