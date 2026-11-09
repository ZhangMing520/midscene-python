"""Minimal MCP server over stdio (upstream agent-tools + docs/mcp.mdx).

Implements the JSON-RPC methods an MCP client needs to discover and call the
Midscene tools: ``initialize``, ``ping``, ``tools/list`` and ``tools/call``.
Each request/response is one JSON object per line on stdin/stdout.
"""

import asyncio
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, TextIO

PROTOCOL_VERSION = "2024-11-05"


def _result(message_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _text_content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False)
    except TypeError:
        return str(payload)


class McpServer:
    """Tool registry plus request handling for the MCP stdio transport."""

    def __init__(self, tools: Iterable[Dict[str, Any]], name: str = "midscene", version: str = "0.2.0"):
        self.tools = {tool["name"]: tool for tool in tools}
        self.name = name
        self.version = version

    def tool_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for tool in self.tools.values()
        ]

    async def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid Request")
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message_id, -32602, "Invalid params")

        if method == "initialize":
            requested = params.get("protocolVersion")
            return _result(
                message_id,
                {
                    # Echo the client version so clients that require an exact
                    # match keep working; fall back to the version we implement.
                    "protocolVersion": (
                        requested if isinstance(requested, str) and requested else PROTOCOL_VERSION
                    ),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            )
        if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return _result(message_id, {})
        if method == "tools/list":
            return _result(message_id, {"tools": self.tool_list()})
        if method == "tools/call":
            return await self._call_tool(message_id, params)
        if message_id is None:
            return None
        return _error(message_id, -32601, f"Method not found: {method}")

    async def _call_tool(
        self, message_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = self.tools.get(name)
        if tool is None:
            return _error(message_id, -32602, f"Unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _error(message_id, -32602, "Tool arguments must be an object")
        try:
            payload = await tool["handler"](arguments)
        except Exception as error:
            return _result(
                message_id,
                {
                    "content": [
                        {"type": "text", "text": f"{type(error).__name__}: {error}"}
                    ],
                    "isError": True,
                },
            )
        return _result(
            message_id,
            {
                "content": [{"type": "text", "text": _text_content(payload)}],
                "isError": False,
            },
        )


async def serve(
    server: McpServer,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> None:
    """Read newline-delimited JSON-RPC requests until stdin closes."""
    reader = stdin or sys.stdin
    writer = stdout or sys.stdout
    while True:
        line = await asyncio.to_thread(reader.readline)
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: Optional[Dict[str, Any]] = _error(None, -32700, "Parse error")
        else:
            try:
                response = await server.handle(message)
            except Exception as error:  # keep serving after an internal failure
                message_id = message.get("id") if isinstance(message, dict) else None
                response = _error(message_id, -32603, f"Internal error: {error}")
        if response is None:
            continue
        writer.write(json.dumps(response, ensure_ascii=False) + "\n")
        writer.flush()


__all__ = ["McpServer", "PROTOCOL_VERSION", "serve"]