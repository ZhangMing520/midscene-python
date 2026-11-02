"""iOS device over WebDriverAgent.

Synced from upstream packages/ios/src/device.ts (v1.17.4). The device
connects to a running WDA server (Appium/XCUITest), takes screenshots via
the W3C screenshot endpoint and drives input through WDA-specific gesture
endpoints. Coordinates are logical points (window size); the screenshot is
physical pixels and the device pixel ratio comes from /wda/screen.
"""

import asyncio
import math
from typing import Any, Dict, List, Optional, Tuple

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

# upstream scrollUntilBoundary timings and geometry
SCROLL_MAX_ATTEMPTS = 20
SCROLL_UNSTABLE_ATTEMPT_LIMIT = 15
SCROLL_SETTLE_MS = 500
SCROLL_INERTIA_MS = 2000
SCROLL_FLING_MS = 300
SCROLL_BOUNDARY_DISTANCE_RATIO = 0.6
SCROLL_UNCHANGED_TOLERANCE_PERCENT = 10
# upstream waitForInputFocus deadline: the keyboard needs a moment after a tap
INPUT_FOCUS_TIMEOUT_MS = 3000


def _screenshots_similar(before: str, after: str, tolerance_percent: float) -> bool:
    """Compare base64 screenshots while tolerating a little dynamic content.

    Upstream compares the encoded text directly: animated clocks and badges
    change a small fraction of the characters, so a threshold on the sampled
    prefix is enough to tell "the page stopped moving" from "still scrolling".
    """
    if before == after:
        return True
    shortest = min(len(before), len(after))
    if not shortest:
        return False
    if abs(len(before) - len(after)) > shortest * 0.1:
        return False
    sample = min(2000, shortest)
    diff_count = sum(1 for i in range(sample) if before[i] != after[i])
    return (diff_count / sample) * 100 <= tolerance_percent


def _default_scroll_gesture(
    direction: str, width: int, height: int
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Start and end of an untargeted scroll (upstream resolveDefaultMobileScroll).

    The gesture crosses the central 70% of the axis so consecutive
    observations keep overlapping content.
    """
    horizontal = direction in ("left", "right")
    forward = direction in ("down", "right")
    extent = width if horizontal else height
    start = round(extent * (0.85 if forward else 0.15))
    end = round(extent * (0.15 if forward else 0.85))
    from_point = [round(width / 2), round(height / 2)]
    to_point = [round(width / 2), round(height / 2)]
    if horizontal:
        from_point[0], to_point[0] = start, end
    else:
        from_point[1], to_point[1] = start, end
    return tuple(from_point), tuple(to_point)


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
        self._screen_scale: Optional[float] = None

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
        """Screen scale from /wda/screen (upstream size().scale)."""
        if self._screen_scale is None:
            scale = await self.wda.get_screen_scale()
            if not scale or scale <= 0:
                raise RuntimeError(
                    "Failed to get device pixel ratio from WebDriverAgent API"
                )
            self._screen_scale = scale
        return self._screen_scale

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
        """Type into the focused element (WDA keys endpoint).

        WDA's keys endpoint appends, so callers that must not keep the old
        content go through replace_input, which clears first.
        """
        await self._ensure_connected()
        await self.wda.type_text(text)

    async def clear_input(self) -> None:
        """Clear the focused field with the W3C element API (upstream clearInputAt)."""
        await self._ensure_connected()
        await self.wda.wait_for_input_focus(INPUT_FOCUS_TIMEOUT_MS)
        if not await self.wda.clear_active_element():
            raise RuntimeError(
                "Cannot verify that input was cleared; refusing to append text"
            )

    async def replace_input(self, text: str) -> None:
        await self.clear_input()
        await self.input_text(text)

    async def keyboard_press(self, key: str) -> None:
        await self._ensure_connected()
        await self.wda.press_key(key)

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret with arrow keys (upstream ios cursorMove); mobile
        devices have no wait between key presses."""
        if direction not in ("left", "right"):
            raise ValueError('CursorMove direction must be "left" or "right"')
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.keyboard_press(arrow_key)

    # -- scroll / swipe ---------------------------------------------------------------

    async def _swipe_coordinates(
        self,
        from_x: float, from_y: float, to_x: float, to_y: float,
        duration: float = 500.0,
    ) -> None:
        """Raw finger path (upstream swipeCoordinates/swipePoint)."""
        await self._ensure_connected()
        await self.wda.swipe(from_x, from_y, to_x, to_y, duration)

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        """Finger-movement convention swipe (content follows the finger)."""
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid swipe direction: {direction}")
        size = await self.size()
        width, height = size["width"], size["height"]
        distance = distance or min(width, height) // 4
        cx, cy = width // 2, height // 2
        # (dx, dy) is the finger movement vector, so the path runs from
        # center - vector/2 to center + vector/2.
        vectors = {
            "up": (0, -distance), "down": (0, distance),
            "left": (-distance, 0), "right": (distance, 0),
        }
        dx, dy = vectors[direction]
        await self._swipe_coordinates(
            cx - dx // 2, cy - dy // 2, cx + dx // 2, cy + dy // 2
        )

    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
        *,
        point: Optional[List[float]] = None,
        scroll_type: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Scroll `direction` names the content to reveal, so the finger moves
        the opposite way (upstream scrollDown swipes upward from the located
        point or the viewport centre).

        scrollType scrollToTop/Bottom/Left/Right keeps flinging until the
        screen stops changing (upstream scrollUntilBoundary).
        """
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")
        boundary = {
            "scrollToTop": "up",
            "scrollToBottom": "down",
            "scrollToLeft": "left",
            "scrollToRight": "right",
        }.get((scroll_type or "").strip())
        if boundary:
            await self._scroll_until_boundary(boundary, point=point)
            return
        size = await self.size()
        width, height = size["width"], size["height"]
        if not distance and not point:
            # upstream scrollDefault: cross the central 70% slowly, so the
            # release velocity stays below the point where iOS flings past the
            # viewport.
            (from_x, from_y), (to_x, to_y) = _default_scroll_gesture(
                direction, width, height
            )
            await self._swipe_coordinates(
                from_x,
                from_y,
                to_x,
                to_y,
                # a fixed duration keeps short gestures from flinging; cap the
                # velocity at 0.4 points per millisecond
                max(1000, round(math.hypot(to_x - from_x, to_y - from_y) / 0.4)),
            )
            return
        # upstream defaults: height/3 vertically, width * 0.7 horizontally
        default = (
            round(height / 3) if direction in ("up", "down") else round(width * 0.7)
        )
        scroll_distance = int(distance) if distance else default
        cx = int(point[0]) if point else width // 2
        cy = int(point[1]) if point else height // 2
        vectors = {
            "down": (0, -scroll_distance), "up": (0, scroll_distance),
            "right": (-scroll_distance, 0), "left": (scroll_distance, 0),
        }
        dx, dy = vectors[direction]
        await self._swipe_coordinates(cx, cy, cx + dx, cy + dy)

    async def _scroll_until_boundary(
        self, direction: str, point: Optional[List[float]] = None
    ) -> None:
        """Fling toward the boundary until the screen stops changing.

        `direction` names the content to reveal, so the finger travels the
        opposite way and starts near the edge that content must cross.
        """
        size = await self.size()
        width, height = size["width"], size["height"]
        if point:
            start_x, start_y = round(point[0]), round(point[1])
        else:
            anchors = {
                "up": (width / 2, height * 0.2),
                "down": (width / 2, height * 0.8),
                "left": (width * 0.8, height / 2),
                "right": (width * 0.2, height / 2),
            }
            start_x, start_y = (round(v) for v in anchors[direction])
        extent = width if direction in ("left", "right") else height
        distance = round(extent * SCROLL_BOUNDARY_DISTANCE_RATIO)
        vectors = {
            "up": (0, distance), "down": (0, -distance),
            "left": (distance, 0), "right": (-distance, 0),
        }
        dx, dy = vectors[direction]
        # upstream only insists on 3 unchanged frames when scrolling right;
        # horizontal carousels settle after one, the rest use a single check.
        max_unchanged = 3 if direction == "right" else 1

        last_screenshot: Optional[str] = None
        unchanged_count = 0
        for attempt in range(SCROLL_MAX_ATTEMPTS):
            await asyncio.sleep(SCROLL_SETTLE_MS / 1000.0)
            current = await self.screenshot_base64()
            if last_screenshot is not None and _screenshots_similar(
                last_screenshot, current, SCROLL_UNCHANGED_TOLERANCE_PERCENT
            ):
                unchanged_count += 1
                if unchanged_count >= max_unchanged:
                    logger.debug(f"Scrolled to {direction}: screen no longer changes")
                    return
            else:
                unchanged_count = 0

            if attempt >= SCROLL_UNSTABLE_ATTEMPT_LIMIT and unchanged_count == 0:
                logger.warning(
                    f"Too many attempts with changing content, stopping scroll to {direction}"
                )
                return

            last_screenshot = current
            await self._swipe_coordinates(
                start_x, start_y, start_x + dx, start_y + dy, SCROLL_FLING_MS
            )
            # wait for the gesture plus its inertia
            await asyncio.sleep(SCROLL_INERTIA_MS / 1000.0)

    async def pinch(
        self,
        direction: str,
        point: Optional[List[float]] = None,
        distance: Optional[int] = None,
        duration: Optional[int] = None,
    ) -> None:
        """Two-finger pinch (upstream normalizePinchParam): "in" pinches the
        fingers together (zoom out / shrink), "out" spreads them apart
        (zoom in / enlarge).

        The fingers start min(width, height)/4 apart and each travels
        `distance` (default: that same base) from there.
        """
        if direction not in ("in", "out"):
            raise ValueError(f'Invalid pinch direction: {direction}. Use "in" or "out"')
        size = await self.size()
        width, height = size["width"], size["height"]
        base = round(min(width, height) / 4)
        finger = int(distance) if distance else base
        center_x = float(point[0]) if point else width / 2
        center_y = float(point[1]) if point else height / 2
        end_distance = base + finger if direction == "out" else max(10, base - finger)
        await self._ensure_connected()
        await self.wda.pinch(
            center_x,
            center_y,
            base,
            end_distance,
            500.0 if duration is None else float(duration),
        )

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

    async def run_wda_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Raw WDA API access (upstream runWdaRequest, the iOS sibling of
        runAdbShell). Returns the parsed WDA response."""
        await self._ensure_connected()
        return await self.wda.execute_request(method, endpoint, data)

    # -- lifecycle -----------------------------------------------------------------

    async def destroy(self) -> None:
        """Drop the WDA session and the HTTP pool (upstream destroy).

        Safe to call twice and before connect(): an absent session or client
        is nothing to release.
        """
        await self.wda.delete_session()
        await self.wda.close()
        self._connected = False
