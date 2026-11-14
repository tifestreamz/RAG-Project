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
