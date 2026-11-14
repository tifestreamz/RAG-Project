"""Managed MCP ClientSession wrapper for stdio and Streamable HTTP transports."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
import json
import os
import sys
import time
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from app_config import PROJECT_ROOT, Settings, get_settings


@dataclass(slots=True)
class DiscoveredTool:
    """Tool metadata returned dynamically by MCP `list_tools()`."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Convert discovered MCP tool schema to Gemini Interactions API tool format."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description or self.name,
            "parameters": self.input_schema or {"type": "object", "properties": {}},
        }


def _extract_tool_payload(result: Any) -> dict[str, Any]:
    """Extract dict payload from MCP `CallToolResult` cleanly."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        # FastMCP / MCPServer wraps single dicts directly or under 'result'
        if set(structured.keys()) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured

    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for item in content:
        txt = getattr(item, "text", None)
        if isinstance(txt, str) and txt.strip():
            texts.append(txt.strip())

    joined = "\n".join(texts).strip()
    if not joined:
        return {"raw": ""}
    try:
        parsed = json.loads(joined)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return {"text": joined}


class MCPClientManager:
    """Async lifecycle and execution manager for the Northstar HR MCP client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        self._discovered_tools: list[DiscoveredTool] = []

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    @property
    def discovered_tools(self) -> list[DiscoveredTool]:
        return list(self._discovered_tools)

    async def connect(self) -> list[DiscoveredTool]:
        """Connect to the configured MCP transport and discover available tools."""
        async with self._lock:
            if self._session is not None and self._discovered_tools:
                return list(self._discovered_tools)
            await self._close_unlocked()

            stack = AsyncExitStack()
            try:
                if self.settings.mcp_transport == "streamable-http":
                    read_s, write_s = await stack.enter_async_context(
                        streamable_http_client(self.settings.mcp_server_url)
                    )
                else:
                    env = os.environ.copy()
                    existing_pp = env.get("PYTHONPATH", "")
                    env["PYTHONPATH"] = (
                        f"{PROJECT_ROOT}{os.pathsep}{existing_pp}"
                        if existing_pp
                        else str(PROJECT_ROOT)
                    )
                    params = StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "mcp_server.server", "--transport", "stdio"],
                        env=env,
                        cwd=str(PROJECT_ROOT),
                    )
                    read_s, write_s = await stack.enter_async_context(
                        stdio_client(params)
                    )

                session = await stack.enter_async_context(
                    ClientSession(read_s, write_s)
                )
                await session.initialize()
                tools_resp = await session.list_tools()
                discovered: list[DiscoveredTool] = []
                for tool in getattr(tools_resp, "tools", []):
                    schema = getattr(tool, "input_schema", None) or getattr(
                        tool, "inputSchema", None
                    ) or {"type": "object", "properties": {}}
                    discovered.append(
                        DiscoveredTool(
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=schema,
                        )
                    )

                self._stack = stack
                self._session = session
                self._discovered_tools = discovered
                return list(self._discovered_tools)
            except Exception:
                await stack.aclose()
                raise

    async def list_tools(self) -> list[DiscoveredTool]:
        """Return dynamically discovered MCP tools, connecting if needed."""
        if self._session is None:
            return await self.connect()
        resp = await self._session.list_tools()
        tools: list[DiscoveredTool] = []
        for tool in getattr(resp, "tools", []):
            schema = getattr(tool, "input_schema", None) or getattr(
                tool, "inputSchema", None
            ) or {"type": "object", "properties": {}}
            tools.append(
                DiscoveredTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=schema,
                )
            )
        self._discovered_tools = tools
        return list(tools)

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Invoke an MCP tool over the active ClientSession and return normalized metadata."""
        t0 = time.perf_counter()
        if self._session is None:
            await self.connect()
        assert self._session is not None

        args = dict(arguments or {})
        try:
            raw_res = await self._session.call_tool(tool_name, args)
            is_error = bool(getattr(raw_res, "is_error", False))
            payload = _extract_tool_payload(raw_res)
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "ok": not is_error and "error" not in payload,
                "tool_name": tool_name,
                "arguments": args,
                "result": payload,
                "duration_ms": duration_ms,
                "error": payload.get("error") if is_error else payload.get("error"),
            }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return {
                "ok": False,
                "tool_name": tool_name,
                "arguments": args,
                "result": {"error": str(exc)},
                "duration_ms": duration_ms,
                "error": str(exc),
            }

    async def _close_unlocked(self) -> None:
        self._session = None
        self._discovered_tools = []
        if self._stack is not None:
            try:
                await self._stack.aclose()
            finally:
                self._stack = None

    async def close(self) -> None:
        """Close active MCP ClientSession and transport subprocess cleanly."""
        async with self._lock:
            await self._close_unlocked()
