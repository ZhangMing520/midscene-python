"""Page driven through the official Chrome extension bridge.

Synced from upstream packages/web-integration/src/bridge-mode (v1.17.4):
the SDK runs a Socket.IO server (io-server.py) on 127.0.0.1:3766; the
Midscene Chrome extension connects as the client and executes page
operations (mouse.*/keyboard.*/screenshotBase64/...) on the active tab.
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.types import (
    AbstractInterface,
    InterfaceType,
    Rect,
    Size,
    UIContext,
    UITree,
    UINode,
    NodeType,
)
from midscene.web_integration.bridge_mode.common import (
    BRIDGE_EVENT_CONNECT_CURRENT_TAB,
    BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL,
    BRIDGE_EVENT_GET_BROWSER_TAB_LIST,
    BRIDGE_EVENT_SET_ACTIVE_TAB_ID,
    BRIDGE_EVENT_UPDATE_AGENT_STATUS,
    DefaultBridgeServerHost,
    DefaultBridgeServerPort,
    get_bridge_server_host,
)
from midscene.web_integration.bridge_mode.io_server import BridgeServer
from midscene.web_integration.web_page import build_key_commands


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
        self.host = get_bridge_server_host(host, allow_remote_access)
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

    async def swipe_points(
        self,
        start: List[float],
        end: List[float],
        duration: Optional[int] = None,
    ) -> None:
        """Endpoint pointer swipe between two points (upstream swipe)."""
        await self.drag_and_drop((start[0], start[1]), (end[0], end[1]))

    async def size(self) -> Dict[str, int]:
        """Logical page size reported by the bridge (upstream size())."""
        size = await self._require_server().call("size", [])
        return {"width": int(size["width"]), "height": int(size["height"])}

    async def input_text(self, text: str) -> None:
        await self._require_server().call("keyboard.type", [text])

    async def keyboard_press(self, key: str) -> None:
        await self._require_server().call(
            "keyboard.press", [build_key_commands(key)]
        )

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret inside the focused field (upstream web cursorMove)."""
        if direction not in ("left", "right"):
            raise ValueError(f"Invalid cursor direction: {direction}")
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.keyboard_press(arrow_key)
            await asyncio.sleep(0.1)

    async def clear_input(self) -> None:
        """Clear the focused field through the extension keyboard channel."""
        await self.keyboard_press("Control+A")
        await self.keyboard_press("Delete")

    async def pinch(
        self,
        center: List[float],
        start_distance: float,
        end_distance: float,
        duration: Optional[int] = None,
    ) -> None:
        """Two-finger pinch around `center` (upstream pinch primitive)."""
        server = self._require_server()
        await server.call(
            "pinch",
            [
                center[0],
                center[1],
                start_distance,
                end_distance,
                duration if duration is not None else 500,
            ],
        )

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")
        server = self._require_server()
        horizontal = direction in ("left", "right")
        point = kwargs.get("point")
        if distance is None or not point:
            size = await server.call("size", [])
            if distance is None:
                distance = (
                    size["width"] if horizontal else size["height"]
                ) * 0.7
            if not point:
                await server.call(
                    "mouse.move", [size["width"] // 2, size["height"] // 2]
                )
        elif point:
            await server.call("mouse.move", [point[0], point[1]])
        if direction == "down":
            delta_x, delta_y = 0, distance
        elif direction == "up":
            delta_x, delta_y = 0, -distance
        elif direction == "right":
            delta_x, delta_y = distance, 0
        else:
            delta_x, delta_y = -distance, 0
        await server.call("mouse.wheel", [delta_x, delta_y])

    async def evaluate_javascript(self, script: str) -> Any:
        """Evaluate JavaScript through the extension's debugger channel."""
        return await self._require_server().call("evaluateJavaScript", [script])

    async def navigate_to(self, url: str) -> None:
        await self._require_server().call("navigate", [url])

    async def reload(self) -> None:
        await self._require_server().call("reload", [])

    async def go_back(self) -> None:
        await self._require_server().call("goBack", [])

    async def go_forward(self) -> None:
        await self._require_server().call("goForward", [])

    async def get_browser_tab_list(self) -> Any:
        return await self._require_server().call(
            BRIDGE_EVENT_GET_BROWSER_TAB_LIST, []
        )

    async def set_active_tab_id(self, tab_id: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_SET_ACTIVE_TAB_ID, [tab_id]
        )

    async def list_tabs(self) -> Any:
        """Browser tabs reported by the connected extension."""
        return await self.get_browser_tab_list()

    async def switch_tab(self, tab_id: str) -> None:
        """Focus the tab with the given id for later calls."""
        await self.set_active_tab_id(tab_id)

    async def connect_new_tab_with_url(self, url: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_CONNECT_NEW_TAB_WITH_URL, [url, self.connect_options]
        )

    async def update_agent_status(self, message: str) -> None:
        await self._require_server().call(
            BRIDGE_EVENT_UPDATE_AGENT_STATUS, [message]
        )

    # ClearInput goes through the keyboard channel (Control+A + Delete), so it
    # does not need the extension's locate-aware clearInput(element) API.
