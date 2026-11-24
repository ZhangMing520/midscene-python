"""HarmonyOS device: full-screen capture + uitest-driven input.

Synced from upstream packages/harmony/src/device.ts (v1.17.4). Coordinates
are device render pixels (foldable-aware); fling endpoints keep a margin
from screen edges because uitest ignores boundary flings.
"""

import asyncio
import base64
import math
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from loguru import logger

from midscene.core.device.mobile_scroll import resolve_default_mobile_scroll
from midscene.core.types import (
    AbstractInterface,
    InterfaceType,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)
from midscene.harmony.hdc import HdcClient
from midscene.harmony.keycode import resolve_harmony_key_codes
from midscene.harmony.swipe import resolve_swipe_speed
from midscene.shared.utils import (
    merge_and_normalize_app_name_mapping,
    normalize_for_comparison,
)

SCREEN_EDGE_MARGIN = 50
DEFAULT_FAST_SWIPE_SPEED = 2000


def _assert_scroll_direction(
    start: Sequence[float],
    end: Sequence[float],
    direction: str,
    size: dict[str, int],
) -> None:
    """Keep the located origin and reject reverse or stationary gestures."""
    start_x, start_y = float(start[0]), float(start[1])
    end_x, end_y = float(end[0]), float(end[1])
    width, height = size["width"], size["height"]
    if not all(
        math.isfinite(value) for value in (start_x, start_y, end_x, end_y)
    ) or not (0 <= start_x < width and 0 <= start_y < height):
        raise ValueError("Scroll origin must be finite and inside the viewport")

    travel = {
        "down": start_y - end_y,
        "up": end_y - start_y,
        "left": end_x - start_x,
        "right": start_x - end_x,
    }[direction]
    if not math.isfinite(travel) or travel <= 0:
        raise ValueError(
            f"No space to scroll {direction} from the located point; "
            "choose a point farther from the screen edge"
        )


MAX_SCROLL_DISTANCE = 9999999


class HarmonyDevice(AbstractInterface):
    """HarmonyOS device driven through the hdc CLI + uitest service."""

    def __init__(
        self,
        device_id: str = "",
        options: Any | None = None,
        hdc_path: str | None = None,
        hdc_timeout: float = 60.0,
    ):
        if isinstance(options, str):
            hdc_path = options
        elif isinstance(options, dict):
            hdc_path = options.get("hdcPath", options.get("hdc_path", hdc_path))
            timeout_value = options.get("hdcTimeout", options.get("hdc_timeout"))
            if timeout_value is not None:
                hdc_timeout = float(timeout_value)
        self.device_id = device_id or ""
        self._hdc_path = hdc_path
        self._hdc_timeout = hdc_timeout
        self.hdc: HdcClient | None = None
        self._connected = False
        self.cached_screen_size: dict[str, int] | None = None
        self._remote_screenshot_path = "/data/local/tmp/midscene-screenshot.jpeg"
        self._local_screenshot_path: Path | None = None
        self._app_name_mapping: dict[str, str] = {}

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
            logger.warning(f"device {self.device_id} not in hdc targets: {targets}")
        self._connected = True
        return self.hdc

    async def _get_hdc(self) -> HdcClient:
        if self.hdc is None:
            await self.connect()
        assert self.hdc is not None
        return self.hdc

    def describe(self) -> str:
        """Human-readable device description (upstream describe)."""
        return f"DeviceId: {self.device_id}"

    async def get_hdc(self) -> HdcClient:
        """Current HDC client, connecting on first use (upstream getHdc)."""
        return await self._get_hdc()

    async def get_context(self) -> UIContext:
        screenshot = await self.screenshot_base64()
        size = await self.size()
        return UIContext(
            screenshot_base64=screenshot,
            size=Size(width=size["width"], height=size["height"]),
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

    async def action_space(self) -> list[str]:
        return ["tap", "input", "key_press", "scroll", "swipe", "long_press", "drag"]

    async def size(self) -> dict[str, int]:
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
            self._local_screenshot_path = (
                Path(tempfile.gettempdir())
                / f"midscene-harmony-screenshot-{self.device_id or 'local'}.jpeg"
            )

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

            await hdc.file_recv(
                self._remote_screenshot_path, str(self._local_screenshot_path)
            )
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

    async def clear_input(self) -> None:
        """Select-all + delete in the focused field (upstream clearInput)."""
        hdc = await self._get_hdc()
        await hdc.clear_text_field()

    # -- scroll / swipe -----------------------------------------------------------

    async def scroll(
        self, direction: str, distance: int | None = None, **kwargs
    ) -> None:
        """Scroll in direction (content direction, upstream scrollInDirection).

        Untargeted scrolls cross the central 70% slowly; scrollTo* repeats a
        fast fling toward the edge, then waits for the screen to settle.
        """
        hdc = await self._get_hdc()
        size = await self.size()
        width, height = size["width"], size["height"]
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")

        scroll_type = kwargs.get("scroll_type") or "singleAction"
        point = kwargs.get("point")
        if point is not None and (
            len(point) < 2
            or not all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in point[:2]
            )
        ):
            raise ValueError("Scroll origin must be a finite point inside the viewport")
        if scroll_type.startswith("scrollTo"):
            boundary = {
                "scrollToTop": "up",
                "scrollToBottom": "down",
                "scrollToLeft": "left",
                "scrollToRight": "right",
            }.get(scroll_type)
            if boundary is None:
                raise ValueError(f"Unknown scroll type: {scroll_type}")
            await self._scroll_until_edge(hdc, boundary, width, height, point)
            return

        if distance is None and not point:
            # Upstream scrollDefault: from 0.85 to 0.15 of the axis.
            (fx, fy), (tx, ty) = resolve_default_mobile_scroll(
                direction, {"width": width, "height": height}
            )
            await hdc.fling(
                fx,
                fy,
                tx,
                ty,
                resolve_swipe_speed({"x": fx, "y": fy}, {"x": tx, "y": ty}, 1000),
            )
            return

        vertical = direction in ("up", "down")
        scroll_distance = int(distance) if distance else (height if vertical else width)
        if point:
            sx, sy = int(point[0]), int(point[1])
            endpoints = {
                "down": (sx, max(SCREEN_EDGE_MARGIN, sy - scroll_distance)),
                "up": (sx, min(height - SCREEN_EDGE_MARGIN, sy + scroll_distance)),
                "left": (min(width - SCREEN_EDGE_MARGIN, sx + scroll_distance), sy),
                "right": (max(SCREEN_EDGE_MARGIN, sx - scroll_distance), sy),
            }
            ex, ey = endpoints[direction]
            _assert_scroll_direction(
                (sx, sy), (ex, ey), direction, {"width": width, "height": height}
            )
            await hdc.fling(sx, sy, ex, ey, DEFAULT_FAST_SWIPE_SPEED)
            return

        deltas = {
            "down": (0, scroll_distance),
            "up": (0, -scroll_distance),
            "left": (-scroll_distance, 0),
            "right": (scroll_distance, 0),
        }
        dx, dy = deltas[direction]
        cx, cy = width // 2, height // 2
        await hdc.fling(cx, cy, cx - dx, cy - dy, DEFAULT_FAST_SWIPE_SPEED)

    async def _scroll_until_edge(
        self,
        hdc: HdcClient,
        direction: str,
        width: int,
        height: int,
        point: list[float] | None,
    ) -> None:
        """Upstream scrollUntilEdge: 10 flings + 1s settle."""
        sx, sy = (int(point[0]), int(point[1])) if point else (width // 2, height // 2)
        targets = {
            "up": (sx, height - SCREEN_EDGE_MARGIN),
            "down": (sx, SCREEN_EDGE_MARGIN),
            "left": (width - SCREEN_EDGE_MARGIN, sy),
            "right": (SCREEN_EDGE_MARGIN, sy),
        }
        tx, ty = targets[direction]
        if point:
            _assert_scroll_direction(
                (sx, sy),
                (tx, ty),
                direction,
                {"width": width, "height": height},
            )
        for _ in range(10):
            await hdc.fling(sx, sy, tx, ty, DEFAULT_FAST_SWIPE_SPEED)
        await asyncio.sleep(1)

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret with Arrow key events (upstream harmony cursorMove)."""
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.keyboard_press(arrow_key)

    async def swipe(self, direction: str, distance: int | None = None) -> None:
        """Finger-movement convention swipe (content follows the finger)."""
        size = await self.size()
        distance = distance or size["width"] // 4
        cx, cy = size["width"] // 2, size["height"] // 2
        # Finger-movement convention: for "up" the finger moves upward,
        # so the start point is below the end point.
        offsets = {
            "up": (0, distance),
            "down": (0, -distance),
            "right": (-distance, 0),
            "left": (distance, 0),
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

    async def swipe_points(
        self,
        start: list[float],
        end: list[float],
        duration: int | None = None,
    ) -> None:
        """Endpoint swipe between two logical points (upstream swipe(start, end))."""
        hdc = await self._get_hdc()
        duration_ms = int(duration if duration is not None else 300)
        speed = resolve_swipe_speed(
            {"x": start[0], "y": start[1]}, {"x": end[0], "y": end[1]}, duration_ms
        )
        await hdc.swipe(start[0], start[1], end[0], end[1], speed)

    async def drag_and_drop(self, from_point, to_point) -> None:
        hdc = await self._get_hdc()
        await hdc.drag(
            from_point[0],
            from_point[1],
            to_point[0],
            to_point[1],
            resolve_swipe_speed(
                {"x": from_point[0], "y": from_point[1]},
                {"x": to_point[0], "y": to_point[1]},
                600,
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
        # upstream recentApps gesture-free path: API 18+ Recent keycode
        await hdc.key_event("10011")

    def set_app_name_mapping(self, mapping: dict[str, str]) -> None:
        """Set the friendly app name -> bundle/ability mapping (upstream
        setAppNameMapping)."""
        self._app_name_mapping = merge_and_normalize_app_name_mapping({}, mapping)

    def _resolve_mapped_app_target(self, app_name: str) -> str | None:
        return self._app_name_mapping.get(normalize_for_comparison(app_name))

    def _resolve_bundle_name_for_terminate(self, target: str) -> str:
        mapped = self._resolve_mapped_app_target(target)
        if mapped:
            return mapped.split("/", 1)[0]
        bundle_or_name = target.split("/", 1)[0]
        return (
            self._resolve_mapped_app_target(bundle_or_name) or bundle_or_name
        ).split("/", 1)[0]

    async def launch_app(self, uri: str) -> None:
        """Launch an app by friendly name, bundle, bundle/ability or URI."""
        target = uri if "://" in uri else (self._resolve_mapped_app_target(uri) or uri)
        hdc = await self._get_hdc()
        if "://" in target:
            sanitized = re.sub(r"[`$\\;\"'|&<>(){}]", "", target)
            await hdc.shell(f"aa start -U {sanitized}")
        elif "/" in target:
            bundle_name, ability_name = target.split("/", 1)
            await hdc.start_ability(bundle_name, ability_name)
        else:
            await hdc.launch(target)

    async def launch(self, uri: str) -> "HarmonyDevice":
        """Launch an app or URI and return this device (upstream launch)."""
        await self.launch_app(uri)
        return self

    async def stop_app(self, bundle_name: str) -> None:
        resolved = self._resolve_bundle_name_for_terminate(bundle_name)
        hdc = await self._get_hdc()
        await hdc.force_stop(resolved)

    async def run_hdc_shell(self, command: str) -> str:
        if not command or not command.strip():
            raise RuntimeError("RunHdcShell requires a non-empty command")
        hdc = await self._get_hdc()
        return await hdc.shell(command)


UI_FAST_SWIPE_SPEED = DEFAULT_FAST_SWIPE_SPEED
