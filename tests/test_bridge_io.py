"""Synced from upstream packages/web-integration/tests/unit-test/bridge/io.test.ts."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestBridgeIo:
    class RecordingServer:
        def __init__(self):
            self.calls: list[tuple] = []

        async def call(self, method, args=None, timeout=None):
            self.calls.append((method, args))
            if method == "size":
                return {"width": 100, "height": 50}
            if method == "screenshotBase64":
                return "data:image/jpeg;base64,AAAA"
            return None

    def _connected_page(self):
        from midscene.web_integration.bridge_mode import BridgeWebPage

        page = BridgeWebPage()
        recorder = self.RecordingServer()
        page._server = recorder
        page._connected = True
        return page, recorder

    @pytest.mark.asyncio
    async def test_bridge_call_response_round_trip(self):
        """Extension client receives bridge-call and its response resolves
        the server-side call (Socket.IO protocol)."""
        import socketio

        from midscene.web_integration.bridge_mode import BridgeServer

        # listen() on an ephemeral port: exercises the real server config
        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]

        received: list = []

        client = socketio.AsyncClient()

        @client.on("bridge-call")
        async def on_call(data):
            received.append(data)
            await client.emit(
                "bridge-call-response",
                {"id": data["id"], "response": {"clicked": True}},
            )

        import aiohttp

        session = aiohttp.ClientSession(
            headers={"Origin": "chrome-extension://testext"}
        )
        client.eio.http = session
        try:
            await client.connect(
                f"ws://127.0.0.1:{port}",
                transports=["websocket"],
                socketio_path="socket.io",
            )
            for _ in range(100):
                if server._client_sid is not None:
                    break
                await asyncio.sleep(0.02)
            assert server._client_sid is not None

            response = await server.call("mouse.click", [10, 20], timeout=5)
            assert response == {"clicked": True}
            assert received[0]["method"] == "mouse.click"
            assert received[0]["args"] == [10, 20]
        finally:
            await client.disconnect()
            await session.close()
            await server.close()

    @pytest.mark.asyncio
    async def test_bridge_listen_timeout_without_client(self):
        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer(port=0)
        with pytest.raises(RuntimeError) as exc:
            await server.listen(timeout=0.3)
        assert "no extension connected" in str(exc.value)

    @pytest.mark.asyncio
    async def test_mouse_primitives_map_to_extension_arguments(self):
        page, recorder = self._connected_page()
        await page.right_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"button": "right"}])
        await page.middle_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"button": "middle"}])
        await page.double_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"count": 2}])
        await page.drag_and_drop((1, 2), (3, 4))
        assert recorder.calls[-1] == (
            "mouse.drag",
            [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
        )
        await page.long_press(5, 6)
        assert recorder.calls[-1] == ("longPress", [5, 6, 1000])

    @pytest.mark.asyncio
    async def test_pinch_maps_to_extension_arguments(self):
        """Upstream labels: 'in' pinches the fingers together, 'out' spreads
        them apart."""
        page, recorder = self._connected_page()
        await page.pinch([10, 20], 120.0, 20.0)
        assert recorder.calls[-1] == ("pinch", [10, 20, 120.0, 20.0, 500])
        await page.pinch([10, 20], 20.0, 120.0, duration=800)
        assert recorder.calls[-1] == ("pinch", [10, 20, 20.0, 120.0, 800])

    @pytest.mark.asyncio
    async def test_get_context_describes_the_viewport_root(self):
        page, _ = self._connected_page()
        context = await page.get_context()
        assert (context.size.width, context.size.height) == (100, 50)
        assert context.tree.node.rect.width == 100
        assert context.tree.node.center == (50, 25)

    @pytest.mark.asyncio
    async def test_page_methods_require_connect(self):
        from midscene.web_integration.bridge_mode import BridgeWebPage

        page = BridgeWebPage()
        with pytest.raises(RuntimeError, match="not connected"):
            await page.tap(1, 2)

    @pytest.mark.asyncio
    async def test_close_flushes_pending_calls(self):
        from types import SimpleNamespace

        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        server._client_sid = "sid"
        server._sio = SimpleNamespace(emit=AsyncMock())
        task = asyncio.create_task(server.call("mouse.click", [1, 2], timeout=30))
        await asyncio.sleep(0.05)
        await server.close()
        with pytest.raises(RuntimeError, match="Bridge server closed"):
            await task

    @pytest.mark.asyncio
    async def test_disconnect_flushes_pending_calls(self):
        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        server._client_sid = "sid"
        loop = asyncio.get_running_loop()
        pending = loop.create_future()
        server._pending["1"] = pending
        await server._on_disconnect("sid")
        with pytest.raises(RuntimeError, match="Connection lost"):
            await pending

    @pytest.mark.asyncio
    async def test_listen_kills_conflicting_server_on_the_real_port(self):
        import socket as _socket

        from midscene.web_integration.bridge_mode import io_server as bridge_module

        probe = _socket.socket()
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()

        seen: list[tuple] = []

        async def fake_kill(port, host):
            seen.append((port, host))

        with patch.object(bridge_module, "kill_running_server", fake_kill):
            server = bridge_module.BridgeServer(host="127.0.0.1", port=free_port)
            await server.listen(timeout=False)
            try:
                assert seen == [(free_port, "127.0.0.1")]
            finally:
                await server.close()

            ephemeral = bridge_module.BridgeServer(host="127.0.0.1", port=0)
            await ephemeral.listen(timeout=False)
            try:
                assert seen == [(free_port, "127.0.0.1")]  # no kill for port 0
            finally:
                await ephemeral.close()

    @pytest.mark.asyncio
    async def test_second_client_receives_bridge_refused(self):
        import socketio

        from midscene.web_integration.bridge_mode import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]

        sessions = []

        def make_client():
            import aiohttp

            client = socketio.AsyncClient()
            session = aiohttp.ClientSession(
                headers={"Origin": "chrome-extension://testext"}
            )
            sessions.append(session)
            client.eio.http = session
            return client

        refused = asyncio.Event()

        first = make_client()
        second = make_client()

        @second.on("bridge-refused")
        async def _on_refused(*args):
            refused.set()

        try:
            await first.connect(
                f"ws://127.0.0.1:{port}",
                transports=["websocket"],
                socketio_path="socket.io",
            )
            for _ in range(100):
                if server._client_sid is not None:
                    break
                await asyncio.sleep(0.02)
            assert server._client_sid is not None

            await second.connect(
                f"ws://127.0.0.1:{port}",
                transports=["websocket"],
                socketio_path="socket.io",
            )
            try:
                await asyncio.wait_for(refused.wait(), timeout=3)
            except TimeoutError:
                pytest.fail("the second client never received bridge-refused")
        finally:
            for client in (first, second):
                try:
                    await client.disconnect()
                except Exception:
                    pass
            for session in sessions:
                await session.close()
            await server.close()
