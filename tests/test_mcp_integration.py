"""Real MCP stdio integration tests validating list_tools() and call_tool()."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from agent.compliance import MockHRDataStore
from app_config import PROJECT_ROOT, Settings
from mcp_server.client import MCPClientManager


@pytest.mark.asyncio
async def test_mcp_stdio_discovery_and_tool_calls() -> None:
    client = MCPClientManager()
    try:
        tools = await client.connect()
        names = {t.name for t in tools}
        expected = {
            "search_policy_documents",
            "get_policy_section",
            "lookup_employee_profile",
            "check_pto_balance",
            "lookup_benefits_status",
            "check_policy_compliance",
            "draft_hr_email",
            "create_mock_hr_ticket",
        }
        assert expected.issubset(names)

        emp_res = await client.call_tool(
            "lookup_employee_profile", {"employee_id": "EMP-1042"}
        )
        assert emp_res["ok"]
        assert emp_res["result"]["employee"]["name"] == "Maya Lin"

        comp_res = await client.call_tool(
            "check_policy_compliance",
            {
                "employee_id": "EMP-1042",
                "request_type": "international_remote_work",
                "days_requested": 42,
                "destination_country": "Portugal",
            },
        )
        assert comp_res["ok"]
        assert comp_res["result"]["status"] == "NON_COMPLIANT"
        assert comp_res["result"]["recommended_priority"] == "P2"

        preview = await client.call_tool(
            "create_mock_hr_ticket",
            {
                "employee_id": "EMP-1042",
                "category": "remote_work",
                "priority": "P2",
                "summary": "Test preview only",
                "policy_references": ["POL-003"],
                "confirmed": False,
            },
        )
        assert preview["ok"]
        assert preview["result"]["persisted"] is False
        assert preview["result"]["requires_confirmation"] is True
    finally:
        await client.close()


def test_confirmed_mock_ticket_persists_with_flag(tmp_path: Path) -> None:
    mock_copy = tmp_path / "mock_data"
    shutil.copytree(PROJECT_ROOT / "mock_data", mock_copy)
    store = MockHRDataStore(Settings(mock_data_dir=mock_copy))
    initial_count = len(store.list_tickets())

    res = store.create_mock_ticket(
        employee_id="EMP-1018",
        category="pto_exception",
        priority="P3",
        summary="Confirmed test synthetic ticket",
        policy_references=["POL-001", "POL-002"],
        confirmed=True,
    )
    assert res["persisted"] is True
    assert res["ticket"]["is_mock"] is True
    assert len(store.list_tickets()) == initial_count + 1
    persisted_json = json.loads((mock_copy / "tickets.json").read_text(encoding="utf-8"))
    assert persisted_json["tickets"][-1]["is_mock"] is True
