"""End-to-end agentic workflow tests across multi-step HR scenarios via real MCP."""

from __future__ import annotations

import pytest

from agent.orchestrator import AgentOrchestrator
from mcp_server.client import MCPClientManager


@pytest.mark.asyncio
async def test_multi_step_agentic_workflows() -> None:
    mcp_client = MCPClientManager()
    await mcp_client.connect()
    orch = AgentOrchestrator(mcp_client)
    try:
        # Demo Task 1: Maya Lin (EMP-1042) 6-week Lisbon workcation
        d1 = await orch.handle_query(
            "Can Maya Lin (EMP-1042) take a 6-week remote workcation from Lisbon, Portugal?",
            provider_override="mock",
        )
        assert d1["status"] == "completed"
        tools_1 = [s["tool_name"] for s in d1["trace"]]
        assert "lookup_employee_profile" in tools_1
        assert "check_pto_balance" in tools_1
        assert "check_policy_compliance" in tools_1
        assert "draft_hr_email" in tools_1
        assert "create_mock_hr_ticket" in tools_1
        assert "NON_COMPLIANT" in d1["answer"]
        assert d1["pending_confirmation"]["priority"] == "P2"

        # Demo Task 2: Carlos Vega (EMP-1018) Dec 21 PTO + Winter Recharge + Mock Ticket
        d2 = await orch.handle_query(
            "Carlos Vega (EMP-1018) wants to take 5 PTO days starting Dec 21 and prepare a mock HR ticket.",
            provider_override="mock",
        )
        assert d2["status"] == "completed"
        assert "CONDITIONAL_APPROVAL" in d2["answer"]
        assert "Winter Recharge" in d2["answer"]
        doc_ids_2 = {c["doc_id"] for c in d2["citations"]}
        assert "POL-001" in doc_ids_2 and "POL-002" in doc_ids_2
        assert d2["pending_confirmation"]["priority"] == "P3"

        # Prod-Admin Loaner Laptop workflow (EMP-1055)
        liam = await orch.handle_query(
            "Liam O'Connor (EMP-1055) wants 10 days remote from Madrid with 20 days notice.",
            provider_override="mock",
        )
        assert "Clean Travel Loaner Laptop" in liam["answer"]
        assert liam["pending_confirmation"]["priority"] == "P2"

        # Contractor ineligibility (EMP-1089)
        contractor = await orch.handle_query(
            "Can contractor Jordan Brooks (EMP-1089) take 3 PTO days?",
            provider_override="mock",
        )
        assert "NON_COMPLIANT" in contractor["answer"]
        assert "POL-012" in contractor["answer"]

        # P1 Confidential Anti-Retaliation Ethics triage (never CC manager)
        p1 = await orch.handle_query(
            "An employee reports manager retaliation and harassment after raising an expense concern.",
            provider_override="mock",
        )
        assert p1["draft_email"]["to"] == "ethics@northstarcloud.example"
        assert p1["draft_email"]["cc"] == []
        assert p1["pending_confirmation"]["priority"] == "P1"
    finally:
        await mcp_client.close()
