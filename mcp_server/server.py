"""MCP Server exposing Northstar HR Policy RAG & Operations tools over stdio or Streamable HTTP."""

from __future__ import annotations

import argparse
import asyncio

from mcp.server.mcpserver import MCPServer

from mcp_server.tools import (
    check_policy_compliance,
    check_pto_balance,
    create_mock_hr_ticket,
    draft_hr_email,
    get_policy_section,
    lookup_benefits_status,
    lookup_employee_profile,
    search_policy_documents,
)


def create_mcp_server() -> MCPServer:
    """Create and register all 8 Northstar HR tools on an `MCPServer` instance."""
    server = MCPServer(
        name="northstar-hr-mcp",
        instructions=(
            "Northstar Cloud Labs HR Policy & Operations MCP server. "
            "Use policy search/section tools for factual rules and mock HR tools "
            "for employee records, compliance checks, drafts, and confirmed tickets."
        ),
    )
    server.tool()(search_policy_documents)
    server.tool()(get_policy_section)
    server.tool()(lookup_employee_profile)
    server.tool()(check_pto_balance)
    server.tool()(lookup_benefits_status)
    server.tool()(check_policy_compliance)
    server.tool()(draft_hr_email)
    server.tool()(create_mock_hr_ticket)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Northstar HR MCP Server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport protocol (default: stdio).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host bind.")
    parser.add_argument("--port", type=int, default=8001, help="HTTP port bind.")
    args = parser.parse_args()

    mcp_server = create_mcp_server()
    if args.transport == "streamable-http":
        asyncio.run(
            mcp_server.run_streamable_http_async(
                host=args.host,
                port=args.port,
                streamable_http_path="/mcp",
            )
        )
    else:
        mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
