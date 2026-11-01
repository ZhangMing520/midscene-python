"""Bridge mode over the official Midscene Chrome extension.

Synced from upstream packages/web-integration/src/bridge-mode (v1.17.4):
the SDK runs a Socket.IO server (io-server.ts) on 127.0.0.1:3766; the
Midscene Chrome extension connects as the client and executes page
operations (mouse.*/keyboard.*/screenshotBase64/...) on the active tab.

Protocol summary:
- events: bridge-call {id, method, args} (server -> extension),
  bridge-call-response {id, response, error?} (extension -> server),
  bridge-connected {version}, bridge-refused
- connections from non chrome-extension:// origins are rejected (CSWSH)
- a client carrying the MIDSCENE_BRIDGE_SIGNAL_KILL query shuts the server
  down (used to free the port before a new session)
- only one extension client may be connected at a time
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

try:
    import socketio
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "python-socketio is required for bridge mode. "
        "Install with: pip install python-socketio"
    ) from e

from ..core.types import (
    AbstractInterface,
    InterfaceType,
    Rect,
    Size,
    UIContext,
    UITree,
    UINode,
    NodeType,
)

DefaultBridgeServerHost = "127.0.0.1"
DefaultBridgeServerPort = 3766
BridgeCallTimeout = 30000

BRIDGE_EVENT_CALL = "bridge-call"
BRIDGE_EVENT_CALL_RESPONSE = "bridge-call-response"
BRIDGE_EVENT_CONNECTED = "bridge-connected"
BRIDGE_EVENT_REFUSED = "bridge-refused"
BRIDGE_EVENT_UPDATE_AGENT_STATUS = "bridge-update-agent-status"
BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL = "connectNewTabWithUrl"
BRIDGE_EVENT_CONNECT_CURRENT_TAB = "connectCurrentTab"
BRIDGE_EVENT_GET_BROWSER_TAB_LIST = "getBrowserTabList"
BRIDGE_EVENT_SET_ACTIVE_TAB_ID = "setActiveTabId"
BRIDGE_SIGNAL_KILL = "MIDSCENE_BRIDGE_SIGNAL_KILL"


def is_trusted_origin(origin: Optional[str]) -> bool:
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
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
    ):
        self.host = host
        self.port = port
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self._sio: Optional[socketio.AsyncServer] = None
        self._runner = None
        self._site = None
        self._client_sid: Optional[str] = None
        self._connected_event = asyncio.Event()
        self._call_counter = 0
        self._pending: Dict[str, asyncio.Future] = {}
        self._closed = False

    async def listen(self, timeout: Optional[float] = 30.0) -> None:
        """Start the server and wait for an extension connection."""
        self._sio = socketio.AsyncServer(
            async_mode="aiohttp",
            ping_timeout=60,  # tolerate MV3 service worker suspension
            max_http_buffer_size=100 * 1024 * 1024,
            cors_allowed_origins=[],
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
                await asyncio.wait_for(
                    self._connected_event.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                await self.close()
                raise RuntimeError(
                    f"no extension connected after {int(timeout * 1000)}ms "
                    "(no-client-connected)"
                )
        logger.info("one client connected")

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
            await self._sio.emit(BRIDGE_EVENT_REFUSED, to=sid)
            logger.info(
                "refused new connection: server already connected by another client"
            )
            return False

        self._client_sid = sid
        client_version = ""
        for part in query.split("&"):
            if part.startswith("version="):
                client_version = part[len("version="):]
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

    async def _on_disconnect(self, sid: str):
        if sid != self._client_sid:
            return
        self._client_sid = None
        # flush all pending calls with a connection-lost error
        for future in list(self._pending):
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
        self, method: str, args: Optional[List[Any]] = None,
        timeout: float = BridgeCallTimeout / 1000,
    ) -> Any:
        """Invoke a method on the extension side and wait for the response."""
        if self._client_sid is None:
            raise RuntimeError("no bridge client connected")
        self._call_counter += 1
        call_id = str(self._call_counter)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
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


class BridgeWebPage(AbstractInterface):
    """Page interface driven through the official Chrome extension bridge."""

    def __init__(
        self,
        host: str = DefaultBridgeServerHost,
        port: int = DefaultBridgeServerPort,
        connect_options: Optional[Dict[str, Any]] = None,
        listening_timeout: Optional[float] = 30.0,
        allow_remote_access: bool = False,
    ):
        self.host = "0.0.0.0" if allow_remote_access else host
        self.port = port
        self.connect_options = connect_options or {
            "forceSameTabNavigation": True,
            "activateTab": True,
            "enableWaterFlowAnimation": True,
        }
        self.listening_timeout = listening_timeout
        self._server: Optional[BridgeServer] = None
        self._connected = False

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.WEB

    async def connect(self) -> None:
        """Start the bridge server and connect to the current active tab."""
        server = BridgeServer(
            host=self.host,
            port=self.port,
            on_connect=self._on_extension_connected,
        )
        await server.listen(timeout=self.listening_timeout)
        self._server = server
        await server.call(
            BRIDGE_EVENT_CONNECT_CURRENT_TAB, [self.connect_options]
        )
        self._connected = True

    async def _on_extension_connected(self) -> None:
        pass

    async def close(self) -> None:
        if self._server:
            try:
                await self._server.call("destroy", [], 5)
            except Exception as e:
                logger.debug(f"bridge destroy call failed: {e}")
            await self._server.close()
            self._server = None
            self._connected = False

    # -- AbstractInterface ---------------------------------------------------

    async def get_context(self) -> UIContext:
        screenshot = await self._server.call("screenshotBase64", [])
        size = await self._server.call("size", [])
        return UIContext(
            screenshot_base64=screenshot,
            size=Size(width=int(size["width"]), height=int(size["height"])),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root",
                    content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0),
                    node_type=NodeType.CONTAINER,
                )
            ),
        )

    async def action_space(self) -> List[str]:
        return ["tap", "input", "scroll", "key_press", "navigate"]

    async def tap(self, x: float, y: float) -> None:
        await self._server.call("mouse.click", [x, y])

    async def hover(self, x: float, y: float) -> None:
        await self._server.call("mouse.move", [x, y])

    async def input_text(self, text: str) -> None:
        await self._server.call("keyboard.type", [text])

    async def keyboard_press(self, key: str) -> None:
        await self._server.call("keyboard.press", [key])

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        distance = distance or 500
        if direction == "down":
            delta_x, delta_y = 0, distance
        elif direction == "up":
            delta_x, delta_y = 0, -distance
        elif direction == "right":
            delta_x, delta_y = distance, 0
        elif direction == "left":
            delta_x, delta_y = -distance, 0
        else:
            raise ValueError(f"Invalid scroll direction: {direction}")
        await self._server.call("mouse.wheel", [delta_x, delta_y])

    async def navigate_to(self, url: str) -> None:
        await self._server.call("navigate", [url])

    async def get_browser_tab_list(self) -> Any:
        return await self._server.call(BRIDGE_EVENT_GET_BROWSER_TAB_LIST, [])

    async def set_active_tab_id(self, tab_id: str) -> None:
        await self._server.call(BRIDGE_EVENT_SET_ACTIVE_TAB_ID, [tab_id])

    async def connect_new_tab_with_url(self, url: str) -> None:
        await self._server.call(
            BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL, [url, self.connect_options]
        )

    async def update_agent_status(self, message: str) -> None:
        await self._server.call(BRIDGE_EVENT_UPDATE_AGENT_STATUS, [message])
