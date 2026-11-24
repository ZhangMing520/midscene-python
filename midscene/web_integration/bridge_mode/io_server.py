"""Socket.IO server the Chrome extension connects to (upstream io-server.ts)."""

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger

try:
    import socketio
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "python-socketio is required for bridge mode. "
        "Install with: pip install python-socketio"
    ) from e

from midscene.web_integration.bridge_mode.common import (
    BRIDGE_EVENT_CALL,
    BRIDGE_EVENT_CALL_RESPONSE,
    BRIDGE_EVENT_CONNECTED,
    BRIDGE_EVENT_REFUSED,
    BRIDGE_SIGNAL_KILL,
    BridgeCallTimeout,
    DefaultBridgeServerHost,
    DefaultBridgeServerPort,
)


def is_trusted_origin(origin: str | None) -> bool:
    """Only the Midscene Chrome extension (or local processes without an
    Origin header) may connect; browser pages are rejected (CSWSH)."""
    if not origin:
        return True
    return origin.startswith("chrome-extension://")


class BridgeServer:
    """Socket.IO server the Chrome extension connects to (io-server.ts)."""

    def __init__(
        self,
        host: str = DefaultBridgeServerHost,
        port: int = DefaultBridgeServerPort,
        on_connect: Callable | None = None,
        on_disconnect: Callable | None = None,
        close_conflict_server: bool = True,
    ):
        self.host = host
        self.port = port
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.close_conflict_server = close_conflict_server
        self._sio: socketio.AsyncServer | None = None
        self._runner = None
        self._site = None
        self._client_sid: str | None = None
        self._connected_event = asyncio.Event()
        self._call_counter = 0
        self._pending: dict[str, asyncio.Future] = {}
        self._closed = False

    async def listen(self, timeout: float | None = 30.0) -> None:
        """Start the server and wait for an extension connection."""
        if self.close_conflict_server and self.port:
            # upstream io-server.ts: free 3766 from a stale session first
            await kill_running_server(self.port, self.host)

        self._sio = socketio.AsyncServer(
            async_mode="aiohttp",
            ping_timeout=60,  # tolerate MV3 service worker suspension
            max_http_buffer_size=100 * 1024 * 1024,
            # echo the request origin so the extension's initial XHR poll is
            # not blocked; the Socket.IO connect handler still enforces origin
            cors_allowed_origins="*",
            # Node's socket.io sends the CONNECT ack before handing the socket
            # to the listener; without this the bridge-refused event emitted
            # below is dropped by the client along with the failed connect.
            always_connect=True,
        )
        self._sio.on("connect", self._on_connect)
        self._sio.on("disconnect", self._on_disconnect)
        self._sio.on(BRIDGE_EVENT_CALL_RESPONSE, self._on_call_response)

        from aiohttp import web

        app = web.Application()
        self._sio.attach(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await self._site.start()
        except OSError as e:
            raise RuntimeError(f"Bridge Listening Error: {e}") from e

        if timeout is not False and timeout is not None:
            try:
                await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
            except TimeoutError:
                await self.close()
                raise RuntimeError(
                    f"no extension connected after {int(timeout * 1000)}ms "
                    "(no-client-connected)"
                ) from None
            if self._client_sid is None:
                raise RuntimeError(
                    "bridge server was closed before an extension connected"
                )

    async def _on_connect(self, sid: str, environ: dict):
        if self._closed:
            return False
        origin = (environ.get("HTTP_ORIGIN") or "").rstrip("/")
        if not is_trusted_origin(origin):
            logger.debug(f"connection rejected: untrusted origin={origin}")
            return False  # reject the connection

        query = environ.get("QUERY_STRING", "")
        if BRIDGE_SIGNAL_KILL in query:
            logger.warning("kill signal received, closing bridge server")
            asyncio.ensure_future(self.close())
            return False

        if self._client_sid is not None:
            if self._client_alive():
                await self._sio.emit(BRIDGE_EVENT_REFUSED, to=sid)
                logger.info(
                    "refused new connection: server already connected by another client"
                )
                return False
            # upstream io-server.ts: a client that died without a disconnect
            # event must not lock the server forever
            self._client_sid = None

        self._client_sid = sid
        logger.info("one client connected")
        client_version = ""
        for part in query.split("&"):
            if part.startswith("version="):
                client_version = part[len("version=") :]
        logger.info(
            f"Bridge connected, browser-side version v{client_version or 'unknown'}"
        )
        self._connected_event.set()
        if self.on_connect:
            result = self.on_connect()
            if asyncio.iscoroutine(result):
                await result
        if self._sio is not None:
            await self._sio.emit(
                BRIDGE_EVENT_CONNECTED,
                {"version": __import__("midscene").__version__},
                to=sid,
            )

    def _client_alive(self) -> bool:
        """Whether the stored sid still owns a live Socket.IO connection."""
        if self._sio is None or self._client_sid is None:
            return False
        return bool(self._sio.manager.is_connected(self._client_sid, "/"))

    async def _on_disconnect(self, sid: str):
        if sid != self._client_sid:
            return
        self._client_sid = None
        # flush all pending calls with a connection-lost error
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(RuntimeError("Connection lost"))
        self._pending.clear()
        if self.on_disconnect:
            result = self.on_disconnect("transport close")
            if asyncio.iscoroutine(result):
                await result

    async def _on_call_response(self, sid: str, data: dict):
        call_id = str(data.get("id"))
        future = self._pending.get(call_id)
        if future is None or future.done():
            return
        error = data.get("error")
        if error:
            future.set_exception(
                RuntimeError(error if isinstance(error, str) else str(error))
            )
        else:
            future.set_result(data.get("response"))

    async def call(
        self,
        method: str,
        args: list[Any] | None = None,
        timeout: float = BridgeCallTimeout / 1000,
    ) -> Any:
        """Invoke a method on the extension side and wait for the response."""
        if self._client_sid is None:
            raise RuntimeError("no bridge client connected")
        self._call_counter += 1
        call_id = str(self._call_counter)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        await self._sio.emit(
            BRIDGE_EVENT_CALL,
            {"id": call_id, "method": method, "args": args or []},
            to=self._client_sid,
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(call_id, None)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        self._site = None
        self._runner = None
        self._client_sid = None
        # a caller waiting on a response would otherwise block until the
        # per-call timeout expires
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(RuntimeError("Bridge server closed"))
        self._pending.clear()
        self._connected_event.set()


async def kill_running_server(
    port: int = DefaultBridgeServerPort,
    host: str = DefaultBridgeServerHost,
) -> None:
    """Send the kill signal to free the port (upstream killRunningServer)."""
    client = socketio.AsyncClient()
    try:
        await client.connect(
            f"ws://{host}:{port}?{BRIDGE_SIGNAL_KILL}=1",
            transports=["websocket"],
            socketio_path="socket.io",
        )
        await asyncio.sleep(0.3)
        await client.disconnect()
    except Exception as e:
        logger.debug(f"failed to kill port: {e}")
