"""HarmonyOS device: full-screen capture + uitest-driven input.

Synced from upstream packages/harmony/src/device.ts (v1.17.4). Coordinates
are device render pixels (foldable-aware); fling endpoints keep a margin
from screen edges because uitest ignores boundary flings.
"""

import base64
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

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
from .hdc import HdcClient
from .keycode import resolve_harmony_key_codes
from .swipe import resolve_swipe_speed

SCREEN_EDGE_MARGIN = 50
DEFAULT_FAST_SWIPE_SPEED = 2000
MAX_SCROLL_DISTANCE = 9999999


class HarmonyDevice(AbstractInterface):
    """HarmonyOS device driven through the hdc CLI + uitest service."""

    def __init__(
        self,
        device_id: str = "",
        hdc_path: Optional[str] = None,
        hdc_timeout: float = 60.0,
    ):
        self.device_id = device_id or ""
        self._hdc_path = hdc_path
        self._hdc_timeout = hdc_timeout
        self.hdc: Optional[HdcClient] = None
        self._connected = False
        self.cached_screen_size: Optional[Dict[str, int]] = None
        self._remote_screenshot_path = "/data/local/tmp/midscene-screenshot.jpeg"
        self._local_screenshot_path: Optional[Path] = None

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.HARMONY

    async def connect(self) -> HdcClient:
        self.hdc = HdcClient(
            device_id=self.device_id,
            hdc_path=self._hdc_path,
            timeout=self._hdc_timeout,
        )
        # sanity check: device reachable
        targets = await self.hdc.list_targets()
        if self.device_id and targets and self.device_id not in targets:
            logger.warning(
                f"device {self.device_id} not in hdc targets: {targets}"
            )
        self._connected = True
        return self.hdc

    async def _get_hdc(self) -> HdcClient:
        if self.hdc is None:
            await self.connect()
        assert self.hdc is not None
        return self.hdc

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
        return ["tap", "input", "key_press", "scroll", "swipe", "long_press", "drag"]

    async def size(self) -> Dict[str, int]:
        """Cached screen size; snapshot output is the source of truth
        (foldables may report a stale hidumper size)."""
        if self.cached_screen_size:
            return dict(self.cached_screen_size)
        hdc = await self._get_hdc()
        self.cached_screen_size = await hdc.get_screen_info()
        return dict(self.cached_screen_size)

    async def screenshot_base64(self) -> str:
        """snapshot_display on device -> file recv -> base64 JPEG. Updates the
        cached screen size from the snapshot output (upstream)."""
        hdc = await self._get_hdc()
        if not self._local_screenshot_path:
            self._local_screenshot_path = Path(
                tempfile.gettempdir()
            ) / f"midscene-harmony-screenshot-{self.device_id or 'local'}.jpeg"

        for attempt in (1, 2):
            snapshot_output = await hdc.screenshot(self._remote_screenshot_path)
            import re

            dim_match = re.search(r"width\s+(\d+),\s*height\s+(\d+)", snapshot_output)
            if dim_match:
                w, h = int(dim_match.group(1)), int(dim_match.group(2))
                if self.cached_screen_size and (
                    self.cached_screen_size["width"] != w
                    or self.cached_screen_size["height"] != h
                ):
                    logger.info(
                        f"Screen size changed: "
                        f"{self.cached_screen_size['width']}x{self.cached_screen_size['height']} -> {w}x{h}"
                    )
                self.cached_screen_size = {"width": w, "height": h}

            await hdc.file_recv(self._remote_screenshot_path, str(self._local_screenshot_path))
            data = self._local_screenshot_path.read_bytes()
            if data:
                return base64.b64encode(data).decode("ascii")
            logger.warning(f"screenshot attempt {attempt} produced an empty file")
        raise RuntimeError("failed to capture HarmonyOS screenshot")

    # -- pointer primitives -----------------------------------------------------

    async def tap(self, x: float, y: float) -> None:
        hdc = await self._get_hdc()
        await hdc.click(x, y)

    async def double_click(self, x: float, y: float) -> None:
        hdc = await self._get_hdc()
        await hdc.double_click(x, y)

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        hdc = await self._get_hdc()
        await hdc.long_click(x, y)

    async def hover(self, x: float, y: float) -> None:
        # uitest has no standalone move; a click on the same point is a no-op
        # for most targets. Keep pointer semantics via a zero-distance drag.
        hdc = await self._get_hdc()
        await hdc.swipe(x, y, x, y, speed=UI_FAST_SWIPE_SPEED)

    # -- text / keys ------------------------------------------------------------

    async def input_text(self, text: str) -> None:
        raise RuntimeError(
            "HarmonyDevice.input_text requires coordinates; use the Input "
            "action (which locates first) or input_text_at(x, y, text)"
        )

    async def input_text_at(self, x: float, y: float, text: str) -> None:
        """uitest uiInput inputText uses (x, y) to identify the target field
        before typing (upstream)."""
        hdc = await self._get_hdc()
        await hdc.input_text(x, y, text)

    async def keyboard_press(self, key: str) -> None:
        hdc = await self._get_hdc()
        codes = resolve_harmony_key_codes(key)
        await hdc.key_event(*codes)

    # -- scroll / swipe -----------------------------------------------------------

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        """Scroll via fling; boundary-fling fix keeps endpoints off the screen
        edge (upstream scrollInDirection)."""
        hdc = await self._get_hdc()
        size = await self.size()
        width, height = size["width"], size["height"]
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")

        if distance is None:
            # full-viewport fling from the center, edge-margin applied
            cx, cy = width // 2, height // 2
            fling_distance = min(width, height) // 2
            endpoints = {
                "down": (cx, cy + fling_distance, cx, max(SCREEN_EDGE_MARGIN, cy - fling_distance)),
                "up": (cx, cy - fling_distance, cx, min(height - SCREEN_EDGE_MARGIN, cy + fling_distance)),
                "left": (cx + fling_distance, cy, max(SCREEN_EDGE_MARGIN, cx - fling_distance), cy),
                "right": (cx - fling_distance, cy, min(width - SCREEN_EDGE_MARGIN, cx + fling_distance), cy),
            }
            fx, fy, tx, ty = endpoints[direction]
            await hdc.fling(fx, fy, tx, ty, resolve_swipe_speed(
                {"x": fx, "y": fy}, {"x": tx, "y": ty}, 1000
            ))
            return

        scroll_distance = min(int(distance), MAX_SCROLL_DISTANCE)
        cx, cy = width // 2, height // 2
        if direction == "down":
            fx, fy, tx, ty = cx, min(height - SCREEN_EDGE_MARGIN, cy + scroll_distance // 2), cx, max(SCREEN_EDGE_MARGIN, cy + scroll_distance // 2 - scroll_distance)
        elif direction == "up":
            fx, fy, tx, ty = cx, max(SCREEN_EDGE_MARGIN, cy - scroll_distance // 2), cx, min(height - SCREEN_EDGE_MARGIN, cy - scroll_distance // 2 + scroll_distance)
        elif direction == "left":
            fx, fy, tx, ty = min(width - SCREEN_EDGE_MARGIN, cx + scroll_distance // 2), cy, max(SCREEN_EDGE_MARGIN, cx + scroll_distance // 2 - scroll_distance), cy
        else:
            fx, fy, tx, ty = max(SCREEN_EDGE_MARGIN, cx - scroll_distance // 2), cy, min(width - SCREEN_EDGE_MARGIN, cx - scroll_distance // 2 + scroll_distance), cy
        await hdc.fling(fx, fy, tx, ty, DEFAULT_FAST_SWIPE_SPEED)

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        """Finger-movement convention swipe (content follows the finger)."""
        size = await self.size()
        distance = distance or size["width"] // 4
        cx, cy = size["width"] // 2, size["height"] // 2
        # Finger-movement convention: for "up" the finger moves upward,
        # so the start point is below the end point.
        offsets = {
            "up": (0, distance), "down": (0, -distance),
            "right": (-distance, 0), "left": (distance, 0),
        }
        if direction not in offsets:
            raise ValueError(f"Invalid swipe direction: {direction}")
        dx, dy = offsets[direction]
        hdc = await self._get_hdc()
        margin = SCREEN_EDGE_MARGIN
        # start opposite to the movement vector, end along it: for "up"
        # (dy=+distance) start y = cy + d/2 (lower) -> end y = cy - d/2 (upper)
        fx = min(max(cx - dx // 2, margin), size["width"] - margin)
        fy = min(max(cy + dy // 2, margin), size["height"] - margin)
        tx = min(max(cx + dx // 2, margin), size["width"] - margin)
        ty = min(max(cy - dy // 2, margin), size["height"] - margin)
        speed = resolve_swipe_speed({"x": fx, "y": fy}, {"x": tx, "y": ty}, 300)
        await hdc.swipe(fx, fy, tx, ty, speed)

    async def drag_and_drop(self, from_point, to_point) -> None:
        hdc = await self._get_hdc()
        await hdc.drag(
            from_point[0], from_point[1], to_point[0], to_point[1],
            resolve_swipe_speed(
                {"x": from_point[0], "y": from_point[1]},
                {"x": to_point[0], "y": to_point[1]}, 600,
            ),
        )

    # -- system buttons / apps ------------------------------------------------------

    async def back(self) -> None:
        hdc = await self._get_hdc()
        await hdc.key_event("Back")

    async def home(self) -> None:
        hdc = await self._get_hdc()
        await hdc.key_event("Home")

    async def recent_apps(self) -> None:
        hdc = await self._get_hdc()
        # upstream recentApps gesture-free path
        await hdc.key_event("Power")

    async def launch_app(self, uri: str) -> None:
        hdc = await self._get_hdc()
        await hdc.launch(uri)

    async def stop_app(self, bundle_name: str) -> None:
        hdc = await self._get_hdc()
        await hdc.force_stop(bundle_name)

    async def run_hdc_shell(self, command: str) -> str:
        if not command or not command.strip():
            raise RuntimeError("RunHdcShell requires a non-empty command")
        hdc = await self._get_hdc()
        return await hdc.shell(command)


UI_FAST_SWIPE_SPEED = DEFAULT_FAST_SWIPE_SPEED
