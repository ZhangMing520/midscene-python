"""iOS device over WebDriverAgent.

Synced from upstream packages/ios/src/device.ts (v1.17.4). The device
connects to a running WDA server (Appium/XCUITest), takes screenshots via
the W3C screenshot endpoint and drives input through WDA-specific gesture
endpoints. Coordinates are logical points (window size); the screenshot is
physical pixels and the device pixel ratio comes from /wda/screen.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

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
from .wda import WebDriverAgentBackend


class IOSDevice(AbstractInterface):
    """iOS device driven through a running WebDriverAgent server."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8100,
        base_url: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.wda = WebDriverAgentBackend(
            host=host, port=port, base_url=base_url,
            session_id=session_id, timeout=timeout,
        )
        self._connected = False
        self._device_pixel_ratio: Optional[float] = None

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.IOS

    async def connect(self, capabilities: Optional[Dict[str, Any]] = None) -> None:
        """Create (or attach to) a WDA session and apply iOS settings."""
        if self.wda.session_id:
            await self.wda.setup_existing_session()
        else:
            await self.wda.create_session(capabilities)
        self._connected = True
        info = await self.wda.get_device_info()
        if info:
            logger.info(f"iOS device connected: {info}")

    async def _ensure_connected(self) -> None:
        if not self._connected:
            await self.connect()

    async def get_context(self) -> UIContext:
        screenshot = await self.screenshot_base64()
        size = await self.size()
        return UIContext(
            screenshot_base64=screenshot,
            size=Size(width=size["width"], height=size["height"]),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root", content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0), node_type=NodeType.CONTAINER,
                )
            ),
        )

    async def action_space(self) -> List[str]:
        return ["tap", "double_click", "long_press", "input", "key_press", "scroll", "swipe", "pinch"]

    # -- screen -----------------------------------------------------------------

    async def _device_pixel_ratio(self) -> float:
        if self._device_pixel_ratio is None:
            scale = await self.wda.get_screen_scale()
            if not scale or scale <= 0:
                raise RuntimeError(
                    "Failed to get device pixel ratio from WebDriverAgent API"
                )
            self._device_pixel_ratio = scale
        return self._device_pixel_ratio

    async def size(self) -> Dict[str, int]:
        """Logical window size in points (upstream size())."""
        await self._ensure_connected()
        width, height = await self.wda.get_window_size()
        return {"width": width, "height": height}

    async def screenshot_base64(self) -> str:
        """PNG screenshot in physical pixels (upstream screenshotBase64)."""
        await self._ensure_connected()
        raw = await self.wda.take_screenshot()
        return f"data:image/png;base64,{raw}" if not raw.startswith("data:") else raw

    # -- pointer ------------------------------------------------------------------

    async def tap(self, x: float, y: float) -> None:
        await self._ensure_connected()
        await self.wda.tap(x, y)

    async def double_click(self, x: float, y: float) -> None:
        await self._ensure_connected()
        await self.wda.double_tap(x, y)

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        await self._ensure_connected()
        await self.wda.long_press(x, y, duration)

    # -- text / keys -----------------------------------------------------------------

    async def input_text(self, text: str) -> None:
        """Type into the focused element (WDA keys endpoint)."""
        await self._ensure_connected()
        await self.wda.type_text(text)

    async def keyboard_press(self, key: str) -> None:
        await self._ensure_connected()
        await self.wda.press_key(key)

    # -- scroll / swipe ---------------------------------------------------------------

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        """Fling-style scroll via the W3C swipe sequence."""
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")
        size = await self.size()
        distance = distance or min(size["width"], size["height"]) // 2
        cx, cy = size["width"] // 2, size["height"] // 2
        deltas = {
            "down": (0, distance), "up": (0, -distance),
            "right": (distance, 0), "left": (-distance, 0),
        }
        dx, dy = deltas[direction]
        await self.swipe(f"{direction}-scroll", cx - dx // 2, cy - dy // 2, cx + dx // 2, cy + dy // 2)

    async def swipe(
        self, direction: str, from_x: float, from_y: float, to_x: float, to_y: float,
        duration: float = 500.0,
    ) -> None:
        """Direct-coordinate swipe (finger-movement convention)."""
        await self._ensure_connected()
        await self.wda.swipe(from_x, from_y, to_x, to_y, duration)

    async def pinch(
        self, center_x: float, center_y: float,
        direction: str = "in", distance: Optional[int] = None,
    ) -> None:
        """Two-finger pinch: 'in' zooms in (fingers apart), 'out' zooms out."""
        await self._ensure_connected()
        size = await self.size()
        distance = distance or min(size["width"], size["height"]) // 4
        if direction == "in":
            await self.wda.pinch(center_x, center_y, distance, 10.0)
        elif direction == "out":
            await self.wda.pinch(center_x, center_y, 10.0, distance)
        else:
            raise ValueError(f'Invalid pinch direction: {direction}. Use "in" or "out"')

    # -- apps ---------------------------------------------------------------------------

    async def launch_app(self, uri: str) -> None:
        await self._ensure_connected()
        if "://" in uri:
            await self.wda.open_url(uri)
        else:
            await self.wda.launch_app(uri)

    async def stop_app(self, bundle_id: str) -> None:
        await self._ensure_connected()
        await self.wda.terminate_app(bundle_id)

    async def home(self) -> None:
        await self._ensure_connected()
        await self.wda.press_home_button()

    async def app_switcher(self) -> None:
        await self._ensure_connected()
        await self.wda.app_switcher()
