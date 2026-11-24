"""Synced from upstream packages/web-integration/tests/unit-test/bridge/security.test.ts."""

import pytest


class TestBridgeSecurity:
    @pytest.mark.asyncio
    async def test_bridge_rejects_untrusted_origin(self):
        import socketio

        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer()
        sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
        sio.on("connect", server._on_connect)
        sio.on("disconnect", server._on_disconnect)
        sio.on("bridge-call-response", server._on_call_response)

        environ = {"HTTP_ORIGIN": "https://evil.com"}
        result = await server._on_connect("sid1", environ)
        assert result is False  # connection rejected

        # trusted origin connects and sets the client sid
        await server._on_connect(
            "sid2", {"HTTP_ORIGIN": "chrome-extension://testext", "QUERY_STRING": ""}
        )
        assert server._client_sid == "sid2"

    @pytest.mark.asyncio
    async def test_polling_handshake_echoes_extension_origin(self):
        """CORS must stay open at the HTTP layer or the extension's first
        XHR poll (chrome-extension:// origin) is blocked by the browser."""
        import aiohttp

        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]
        try:
            async with aiohttp.ClientSession(
                headers={"Origin": "chrome-extension://testext"}
            ) as session:
                async with session.get(
                    f"http://127.0.0.1:{port}/socket.io/?EIO=4&transport=polling"
                ) as response:
                    assert response.status == 200
                    assert (
                        response.headers.get("Access-Control-Allow-Origin")
                        == "chrome-extension://testext"
                    )
        finally:
            await server.close()
