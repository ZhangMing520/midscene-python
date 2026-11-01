"""Bridge mode over the official Midscene Chrome extension.

Synced from upstream packages/web-integration/src/bridge-mode (v1.17.4):
the SDK runs a Socket.IO server (io-server.ts) on 127.0.0.1:3766; the
Midscene Chrome extension connects as the client and executes page
operations (mouse.*/keyboard.*/screenshotBase64/...) on the active tab.

Protocol summary:
- events: bridge-call {id, method, args} (server -> extension),
  bridge-call-response {id, response, error?} (extension -> server),
  bridge-connected {version}, bridge-refused
- CORS stays open at the HTTP layer (the extension reaches us as a
  chrome-extension:// origin and engine.io starts with an XHR poll); access
  is enforced on the Socket.IO handshake by the origin check below
- a client carrying the MIDSCENE_BRIDGE_SIGNAL_KILL query shuts the server
  down (used to free the port before a new session)
- only one extension client may be connected at a time; a client whose
  transport died without a disconnect event can be replaced
"""

import asyncio
import sys
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


_IS_MAC = sys.platform == "darwin"

# upstream web-page.ts getKeyCommands(): the extension drives CDP
# Input.dispatchKeyEvent, which needs {key, command} objects, not the
# Playwright-style keyName strings the rest of the SDK uses.
_KEY_ALIASES = {
    "return": "Enter",
    "enter": "Enter",
    "command": "Meta",
    "cmd": "Meta",
    "meta": "Meta",
    "shift": "Shift",
    "alt": "Alt",
    "option": "Alt",
    "space": " ",
    "page down": "PageDown",
    "pagedown": "PageDown",
    "page up": "PageUp",
    "pageup": "PageUp",
}

_PRIMARY_MODIFIERS = ("Control", "Meta")

_EDIT_COMMANDS = {
    "a": "SelectAll",
    "c": "Copy",
    "v": "Paste",
}


def _canonical_key(token: str) -> str:
    lowered = token.lower()
    if lowered == "ctrl":
        return "Meta" if _IS_MAC else "Control"
    return _KEY_ALIASES.get(lowered, token)


def build_key_commands(key_name: str) -> List[Dict[str, Any]]:
    """Expand a keyName like 'Control+A' or 'Enter' into the key/command
    objects the Chrome extension expects (upstream normalizeKeyInputs +
    getKeyCommands)."""
    text = key_name.strip()
    whole_phrase = _KEY_ALIASES.get(text.lower())
    if whole_phrase is not None:
        keys = [whole_phrase]
    else:
        if len(text) > 1 and "+" in text:
            text = text.replace("+", " ")
        keys = [_canonical_key(token) for token in text.split()] or [key_name]
    has_primary = any(key in _PRIMARY_MODIFIERS for key in keys)
    commands = []
    for key in keys:
        command = _EDIT_COMMANDS.get(key.lower()) if has_primary else None
        commands.append({"key": key, "command": command} if command else {"key": key})
    return commands


class BridgeServer:
    """Socket.IO server the Chrome extension connects to (io-server.ts)."""

    def __init__(
        self,
        host: str = DefaultBridgeServerHost,
        port: int = DefaultBridgeServerPort,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
        close_conflict_server: bool = True,
    ):
        self.host = host
        self.port = port
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.close_conflict_server = close_conflict_server
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
                await asyncio.wait_for(
                    self._connected_event.wait(), timeout=timeout
                )
            except asyncio.TimeoutError:
                await self.close()
                raise RuntimeError(
                    f"no extension connected after {int(timeout * 1000)}ms "
                    "(no-client-connected)"
                )
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
        self, method: str, args: Optional[List[Any]] = None,
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


class BridgeWebPage(AbstractInterface):
    """Page interface driven through the official Chrome extension bridge."""

    def __init__(
        self,
        host: str = DefaultBridgeServerHost,
        port: int = DefaultBridgeServerPort,
        connect_options: Optional[Dict[str, Any]] = None,
        listening_timeout: Optional[float] = 30.0,
        allow_remote_access: bool = False,
        close_conflict_server: bool = True,
    ):
        self.host = "0.0.0.0" if allow_remote_access else host
        self.port = port
        self.connect_options = connect_options or {
            "forceSameTabNavigation": True,
            "activateTab": True,
            "enableWaterFlowAnimation": True,
        }
        self.listening_timeout = listening_timeout
        self.close_conflict_server = close_conflict_server
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
            close_conflict_server=self.close_conflict_server,
        )
        await server.listen(timeout=self.listening_timeout)
        self._server = server
        await server.call(
            BRIDGE_EVENT_CONNECT_CURRENT_TAB, [self.connect_options]
        )
        self._connected = True

    async def _on_extension_connected(self) -> None:
        pass

    def _require_server(self) -> BridgeServer:
        if self._server is None or not self._connected:
            raise RuntimeError(
                "bridge is not connected, call BridgeWebPage.connect() first"
            )
        return self._server

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
        server = self._require_server()
        screenshot = await server.call("screenshotBase64", [])
        size = await server.call("size", [])
        width = int(size["width"])
        height = int(size["height"])
        return UIContext(
            screenshot_base64=screenshot,
            size=Size(width=width, height=height),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root",
                    content="",
                    rect=Rect(left=0, top=0, width=width, height=height),
                    center=(width / 2, height / 2),
                    node_type=NodeType.CONTAINER,
                )
            ),
        )

    async def action_space(self) -> List[str]:
        return [
            "tap", "right_click", "middle_click", "double_click", "hover",
            "input", "scroll", "key_press", "drag_and_drop", "long_press",
            "pinch", "navigate",
        ]

    async def tap(self, x: float, y: float) -> None:
        await self._require_server().call("mouse.click", [x, y])

    async def right_click(self, x: float, y: float) -> None:
        await self._require_server().call(
            "mouse.click", [x, y, {"button": "right"}]
        )

    async def middle_click(self, x: float, y: float) -> None:
        await self._require_server().call(
            "mouse.click", [x, y, {"button": "middle"}]
        )

    async def double_click(self, x: float, y: float) -> None:
        await self._require_server().call(
            "mouse.click", [x, y, {"count": 2}]
        )

    async def hover(self, x: float, y: float) -> None:
        await self._require_server().call("mouse.move", [x, y])

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        await self._require_server().call("longPress", [x, y, duration])

    async def drag_and_drop(self, from_point, to_point) -> None:
        await self._require_server().call(
            "mouse.drag",
            [{"x": from_point[0], "y": from_point[1]},
             {"x": to_point[0], "y": to_point[1]}],
        )

    async def input_text(self, text: str) -> None:
        await self._require_server().call("keyboard.type", [text])

    async def keyboard_press(self, key: str) -> None:
        await self._require_server().call(
            "keyboard.press", [build_key_commands(key)]
        )

    async def pinch(
        self,
        direction: str,
        point: Optional[List[float]] = None,
        distance: Optional[int] = None,
        duration: Optional[int] = None,
    ) -> None:
        if direction not in ("in", "out"):
            raise ValueError('pinch direction must be "in" or "out"')
        server = self._require_server()
        if point is None:
            size = await server.call("size", [])
            point = [size["width"] / 2, size["height"] / 2]
        spread = float(distance if distance is not None else 100)
        # extension signature: pinch(centerX, centerY, startDistance,
        # endDistance, duration); 'out' brings the fingers together
        start, end = (spread, 20.0) if direction == "out" else (20.0, spread)
        await server.call(
            "pinch",
            [
                point[0],
                point[1],
                start,
                end,
                duration if duration is not None else 500,
            ],
        )

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
        await self._require_server().call("mouse.wheel", [delta_x, delta_y])

    async def navigate_to(self, url: str) -> None:
        await self._require_server().call("navigate", [url])

    async def get_browser_tab_list(self) -> Any:
        return await self._require_server().call(
            BRIDGE_EVENT_GET_BROWSER_TAB_LIST, []
        )

    async def set_active_tab_id(self, tab_id: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_SET_ACTIVE_TAB_ID, [tab_id]
        )

    async def connect_new_tab_with_url(self, url: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL, [url, self.connect_options]
        )

    async def update_agent_status(self, message: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_UPDATE_AGENT_STATUS, [message]
        )

    # TODO(bridge): the extension's clearInput(element) needs a locate-aware
    # ElementInfo argument, so ClearInput stays out of the bridge action space.
