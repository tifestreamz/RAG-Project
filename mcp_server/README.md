# `mcp_server/` — Northstar HR Model Context Protocol Server & Client

This package implements Northstar Cloud Labs' **Model Context Protocol (MCP)** server (`mcp_server/server.py`) and managed client session (`mcp_server/client.py`) built on the official Python `mcp` SDK (`2.3.0`, `MCPServer` + `ClientSession`).

> **Package Naming Note:** The package is named `mcp_server/` (rather than `mcp/`) so Python's module import resolution never shadows the upstream `mcp` PyPI package (`from mcp.server.mcpserver import MCPServer`).

## Transports

- **`stdio` (Default for Render single-service deployment & CI):**
  `MCPClientManager` spawns `python -m mcp_server.server --transport stdio` as a managed subprocess over JSON-RPC standard input/output pipes.
- **`streamable-http` (Optional multi-service deployment):**
  Run `python -m mcp_server.server --transport streamable-http --host 0.0.0.0 --port 8001` and set `MCP_TRANSPORT=streamable-http` and `MCP_SERVER_URL=http://127.0.0.1:8001/mcp`.

## Exposed MCP Tools (8 Tools)

1. **`search_policy_documents(query, top_k=5, category=None, doc_id=None)`** — Hybrid FAISS + BM25 + RRF search across `policies/` with relevance threshold gating.
2. **`get_policy_section(doc_id, section_query="")`** — Direct section lookup from `chunks.db` by policy ID and section filter.
3. **`lookup_employee_profile(employee_id)`** — Synthetic employee directory lookup (`mock_data/employees.json`).
4. **`check_pto_balance(employee_id)`** — PTO remaining balance, floating holidays, rolling 12-month international remote days used, and blackout flags (`mock_data/pto_balances.json`).
5. **`lookup_benefits_status(employee_id)`** — Health tier, 401(k) match, monthly wellness stipend, and L&D budget remaining (`mock_data/benefits.json`).
6. **`check_policy_compliance(employee_id, request_type, days_requested=0, destination_country="", advance_notice_days=None, during_blackout=False, amount_usd=0)`** — Deterministic rule compliance evaluator checking tenure, probation, 30-day rolling caps, sanctions jurisdictions, `Prod-Admin`/`Customer-PII` loaner rules, and P1/P2/P3 routing.
7. **`draft_hr_email(recipient, subject, body, cc_list=None)`** — Generates review-only approval or escalation email drafts (never transmits external emails).
8. **`create_mock_hr_ticket(employee_id, category, priority, summary, policy_references=None, confirmed=False)`** — Previews (`confirmed=False`) or persists (`confirmed=True`) synthetic HR cases (`is_mock: true`) to `mock_data/tickets.json`. Agent turns force `confirmed=False`; persistence occurs only via explicit `/confirm` user approval.
