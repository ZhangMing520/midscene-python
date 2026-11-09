"""Tests for the MCP stdio server (no browser or model required)."""

import asyncio
import io
import json

import pytest

from midscene.mcp_server import McpServer, serve


def _tool(name="demo", handler=None):
    async def default_handler(arguments):
        return {"echo": arguments.get("value")}

    return {
        "name": name,
        "description": "demo tool",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": handler or default_handler,
    }


def _request(method, params=None, message_id=1):
    message = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class TestMcpServer:
    @pytest.mark.asyncio
    async def test_initialize_reports_capabilities(self):
        server = McpServer([_tool()], name="midscene-test", version="9.9.9")
        response = await server.handle(_request("initialize"))

        assert response["id"] == 1
        assert response["result"]["protocolVersion"]
        assert response["result"]["serverInfo"] == {
            "name": "midscene-test",
            "version": "9.9.9",
        }
        assert "tools" in response["result"]["capabilities"]

    @pytest.mark.asyncio
    async def test_initialize_echoes_the_client_protocol_version(self):
        server = McpServer([_tool()])
        response = await server.handle(
            _request("initialize", {"protocolVersion": "2025-06-18"})
        )

        assert response["result"]["protocolVersion"] == "2025-06-18"

    @pytest.mark.asyncio
    async def test_tools_list_hides_handlers(self):
        server = McpServer([_tool()])
        response = await server.handle(_request("tools/list"))

        assert response["result"]["tools"] == [
            {
                "name": "demo",
                "description": "demo tool",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]

    @pytest.mark.asyncio
    async def test_tools_call_returns_text_content(self):
        server = McpServer([_tool()])
        response = await server.handle(
            _request("tools/call", {"name": "demo", "arguments": {"value": 7}})
        )

        assert response["result"]["isError"] is False
        assert json.loads(response["result"]["content"][0]["text"]) == {"echo": 7}

    @pytest.mark.asyncio
    async def test_tool_failure_is_reported_not_raised(self):
        async def failing(arguments):
            raise RuntimeError("browser crashed")

        server = McpServer([_tool(handler=failing)])
        response = await server.handle(
            _request("tools/call", {"name": "demo", "arguments": {}})
        )

        assert response["result"]["isError"] is True
        assert "browser crashed" in response["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_unknown_tool_and_method(self):
        server = McpServer([_tool()])

        unknown_tool = await server.handle(
            _request("tools/call", {"name": "missing", "arguments": {}})
        )
        assert unknown_tool["error"]["code"] == -32602

        unknown_method = await server.handle(_request("resources/read"))
        assert unknown_method["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_notifications_get_no_response(self):
        server = McpServer([_tool()])
        assert await server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        ) is None

    @pytest.mark.asyncio
    async def test_invalid_params_shape_is_rejected(self):
        server = McpServer([_tool()])
        response = await server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": ["unexpected"]}
        )

        assert response["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_invalid_envelope_is_rejected(self):
        server = McpServer([_tool()])
        response = await server.handle({"id": 1, "method": "ping"})
        assert response["error"]["code"] == -32600


class TestServe:
    def test_round_trips_newline_delimited_json(self):
        server = McpServer([_tool()])
        stdin = io.StringIO(
            json.dumps(_request("initialize", message_id=1))
            + "\n"
            + "not json\n"
            + json.dumps(_request("tools/list", message_id=2))
            + "\n"
        )
        stdout = io.StringIO()

        asyncio.run(serve(server, stdin=stdin, stdout=stdout))

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert lines[0]["id"] == 1
        assert lines[1]["error"]["code"] == -32700
        assert lines[2]["result"]["tools"][0]["name"] == "demo"