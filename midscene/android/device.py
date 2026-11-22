"""
Android device management using ADB
"""

import asyncio
import base64
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger
from pydantic import BaseModel

from midscene.android.adb_shell import (
    YADB_DEVICE_PATH,
    YADB_VERSION,
    escape_for_shell,
    shell_escape_arg,
    should_use_yadb_for_text,
)
from midscene.android.ui_tree import parse_ui_automator_xml
from midscene.android.utils import (
    parse_adb_devices_output,
    parse_screen_density,
    parse_screen_size_output,
)
from midscene.core.device.mobile_scroll import resolve_default_mobile_scroll
from midscene.android.adb import create_android_adb, run_adb_command
from midscene.android.scrcpy_device_adapter import ScrcpyDeviceAdapter
from midscene.android.ui_tree_capture import capture_android_ui_tree
from midscene.core.types import (
    AbstractInterface, InterfaceType, UIContext, BaseElement, UINode, UITree,
    Size, Rect, NodeType
)
from midscene.shared.utils import (
    merge_and_normalize_app_name_mapping,
    normalize_for_comparison,
)


class AndroidElement(BaseElement):
    """Android UI element wrapper"""
    
    def __init__(self, device: 'AndroidDevice', **kwargs):
        self._device = device
        super().__init__(**kwargs)
    
    async def tap(self) -> None:
        """Tap this element"""
        try:
            center = self.center
            await self._device.tap(center[0], center[1])
        except Exception as e:
            logger.error(f"Failed to tap element: {e}")
            raise
    
    async def input_text(self, text: str) -> None:
        """Input text to this element"""
        try:
            # First tap to focus
            await self.tap()
            await asyncio.sleep(0.5)
            
            # Clear existing text
            await self._device.clear_text()
            
            # Input new text
            await self._device.input_text(text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise


# ---------------------------------------------------------------------------
# Text input helpers (upstream packages/android/src/device.ts)
# ---------------------------------------------------------------------------

IME_STRATEGY_ALWAYS_YADB = "always-yadb"
IME_STRATEGY_YADB_FOR_NON_ASCII = "yadb-for-non-ascii"
IME_STRATEGY_LEGACY = "legacy"

DEFAULT_SCROLL_UNTIL_TIMES = 10
DEFAULT_FAST_SCROLL_DURATION = 100
DEFAULT_NORMAL_SCROLL_DURATION = 1000


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _round_half_up(value: float) -> int:
    # JS Math.round rounds half toward +infinity, unlike Python's round().
    return int(math.floor(value + 0.5))


def calculate_scroll_end_point(
    start: Sequence[float],
    delta_x: float,
    delta_y: float,
    width: float,
    height: float,
) -> Tuple[int, int]:
    """Clamp an anchored scroll gesture to the viewport (upstream).

    The start point must stay inside the viewport and the requested travel is
    capped so the gesture never overshoots the edge it is heading toward.
    """
    start_x, start_y = float(start[0]), float(start[1])
    if not all(
        _is_finite_number(value)
        for value in (start_x, start_y, delta_x, delta_y, width, height)
    ) or not (
        0 <= start_x <= width and 0 <= start_y <= height
    ):
        raise ValueError(
            "Scroll origin and distance must be finite and inside the viewport"
        )

    if delta_x == 0 and delta_y == 0:
        raise ValueError("Scroll distance is too small to move after rounding")

    def actual_distance(origin: float, delta: float, size: float) -> float:
        # Cap the requested travel at the room toward the edge; a short
        # request is kept as-is so small intentional gestures survive.
        available = size - origin if delta > 0 else origin
        return min(abs(delta), available)

    distance_x = actual_distance(start_x, delta_x, width) if delta_x else 0.0
    distance_y = actual_distance(start_y, delta_y, height) if delta_y else 0.0

    if delta_x == 0:
        end_x = _round_half_up(start_x)
    elif delta_x > 0:
        end_x = _round_half_up(min(width, start_x + distance_x))
    else:
        end_x = _round_half_up(max(0, start_x - distance_x))

    if delta_y == 0:
        end_y = _round_half_up(start_y)
    elif delta_y > 0:
        end_y = _round_half_up(min(height, start_y + distance_y))
    else:
        end_y = _round_half_up(max(0, start_y - distance_y))

    if (delta_x != 0 and (end_x - start_x) * delta_x <= 0) or (
        delta_y != 0 and (end_y - start_y) * delta_y <= 0
    ):
        raise ValueError(
            "No space to scroll from the located point; "
            "choose a point farther from the screen edge"
        )

    return end_x, end_y


# Scroll directions name the content to reveal, i.e. the inverse of the finger
# movement direction used by _swipe_direction. Clamp warnings suggest a scroll
# action, so they must be reported in the scroll convention.
_SCROLL_DIRECTION_FOR_SWIPE = {
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
}


def warn_scroll_distance_clamped(
    direction: str, requested_distance: float, applied_distance: float
) -> None:
    if requested_distance <= applied_distance:
        return

    scroll_to_suggestion = {
        "down": "scrollToBottom",
        "up": "scrollToTop",
        "left": "scrollToLeft",
        "right": "scrollToRight",
    }
    edge_label = {
        "down": "bottom",
        "up": "top",
        "left": "left edge",
        "right": "right edge",
    }
    logger.warning(
        "[midscene] Android ADB swipe coordinates must stay within the screen "
        f"bounds. The requested scroll distance ({requested_distance}px) exceeds "
        "the maximum single swipe distance "
        f"({applied_distance}px) from the current start point, so it will be "
        f"clamped. If you want to scroll to the {edge_label[direction]}, use "
        f"{scroll_to_suggestion[direction]} instead."
    )


class AndroidDeviceConfig(BaseModel):
    """Android device configuration"""
    device_id: str
    adb_path: str = "adb"
    auto_dismiss_keyboard: bool = True
    use_ime: bool = True
    display_id: int = 0
    timeout: int = 30
    # Opt-in scrcpy screenshots (upstream scrcpyConfig). Default off so the
    # existing ADB screencap path is unchanged.
    scrcpy_config: Optional[Dict[str, Any]] = None


def _config_from_options(
    device_id: str, options: Dict[str, Any]
) -> AndroidDeviceConfig:
    """Map upstream AndroidDeviceOpt camelCase keys onto the config."""
    return AndroidDeviceConfig(
        device_id=device_id,
        adb_path=(
            options.get("androidAdbPath")
            or options.get("adbPath")
            or options.get("adb_path")
            or "adb"
        ),
        auto_dismiss_keyboard=options.get(
            "autoDismissKeyboard",
            options.get("auto_dismiss_keyboard", True),
        ),
        use_ime=options.get("useIme", options.get("use_ime", True)),
        display_id=options.get("displayId", options.get("display_id", 0)),
        timeout=options.get("timeout", 30),
        scrcpy_config=options.get(
            "scrcpyConfig", options.get("scrcpy_config")
        ),
    )


class AndroidDevice(AbstractInterface):
    """Android device interface using ADB"""
    
    def __init__(
        self,
        device_id: str,
        config: Optional[Any] = None,
    ):
        """Initialize Android device
        
        Args:
            device_id: Android device ID
            config: Device configuration (AndroidDeviceConfig or an upstream
                AndroidDeviceOpt-style dict)
        """
        self.device_id = device_id
        if isinstance(config, dict):
            config = _config_from_options(device_id, config)
        self.config = config or AndroidDeviceConfig(device_id=device_id)
        self._connected = False
        self._screen_size: Optional[Size] = None
        self._physical_size: Optional[Size] = None
        self._device_pixel_ratio: float = 1.0
        self._yadb_pushed = False
        self._yadb_bin_path: Optional[str] = None
        self._app_name_mapping: Dict[str, str] = {}
        self._scrcpy_adapter: Optional[ScrcpyDeviceAdapter] = None
        self._adb: Optional[Any] = None
        self._description: Optional[str] = None
    
    @classmethod
    async def create(cls, device_id: Optional[str] = None) -> 'AndroidDevice':
        """Create Android device instance
        
        Args:
            device_id: Device ID, if None will use first available device
            
        Returns:
            AndroidDevice instance
        """
        if not device_id:
            devices = await cls.list_devices()
            if not devices:
                raise RuntimeError("No Android devices found")
            device_id = devices[0]
        
        device = cls(device_id)
        await device.connect()
        return device
    
    @classmethod
    async def list_devices(cls) -> List[str]:
        """List available Android devices"""
        try:
            result = await cls._run_adb_command(["devices"])
            return parse_adb_devices_output(result.stdout.strip())
            
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []
    
    async def connect(self) -> None:
        """Connect to Android device"""
        try:
            # Check if device is available
            devices = await self.list_devices()
            if self.device_id not in devices:
                raise RuntimeError(f"Device {self.device_id} not found")
            
            # Get screen size
            await self._get_screen_size()
            if self._screen_size is not None:
                self._description = (
                    f"\nDeviceId: {self.device_id}\nScreenSize:\n"
                    f"  width size: {self._screen_size.width}\n"
                    f"  height size: {self._screen_size.height}\n"
                )
            
            # Setup IME if needed
            if self.config.use_ime:
                await self._setup_ime()

            # Opt-in scrcpy screenshots. A transient failure falls back to the
            # existing ADB path while preserving the ability to retry.
            if self._scrcpy_configured():
                try:
                    await self._get_scrcpy_adapter().initialize()
                    logger.info(
                        f"Using scrcpy for screenshots (device: "
                        f"{self.device_id})"
                    )
                except Exception as e:
                    logger.warning(
                        "Scrcpy unavailable, using ADB fallback "
                        f"(device: {self.device_id}): {e}. Call "
                        "retry_scrcpy() to retry immediately."
                    )

            self._connected = True
            logger.info(f"Connected to Android device: {self.device_id}")
            
        except Exception as e:
            logger.error(f"Failed to connect to device: {e}")
            raise
    
    @property
    def interface_type(self) -> InterfaceType:
        """Get interface type"""
        return InterfaceType.ANDROID

    def _scrcpy_configured(self) -> bool:
        config = self.config.scrcpy_config
        return bool(config and config.get("enabled"))

    def _get_scrcpy_adapter(self) -> ScrcpyDeviceAdapter:
        """Lazily create the scrcpy adapter (upstream getScrcpyAdapter)."""
        if self._scrcpy_adapter is None:
            self._scrcpy_adapter = ScrcpyDeviceAdapter(
                self.device_id,
                self.config.scrcpy_config,
                adb_path=self.config.adb_path,
            )
        return self._scrcpy_adapter

    def get_scrcpy_status(self):
        """Current scrcpy configuration, connection and recovery state."""
        return self._get_scrcpy_adapter().get_status()

    async def retry_scrcpy(self):
        """Retry scrcpy initialization without recreating the device."""
        adapter = self._get_scrcpy_adapter()
        if not adapter.is_configured():
            raise RuntimeError("scrcpy is disabled in AndroidDevice options")
        await adapter.initialize()
        return adapter.get_status()

    # -- upstream public surface ------------------------------------------

    def describe(self) -> str:
        """Human-readable device description (upstream describe)."""
        return self._description or f"DeviceId: {self.device_id}"

    async def get_adb(self) -> Any:
        """Current ADB client (upstream getAdb).

        The Python SDK normally runs adb per command; this exposes the same
        lazily-created client object for callers that need it directly.
        """
        if self._adb is None:
            self._adb = await create_android_adb(
                adb_exec_timeout=60000,
                device_id=self.device_id,
                device_options={
                    "androidAdbPath": self.config.adb_path,
                    "displayId": self.config.display_id,
                },
            )
        return self._adb

    async def ensure_yadb(self) -> None:
        """Push the Yadb tool to the device once (upstream ensureYadb)."""
        await self._ensure_yadb()

    async def exec_yadb(self, keyboard_content: str) -> None:
        """Inject keyboard content through Yadb (upstream execYadb)."""
        await self._exec_yadb_raw(keyboard_content)

    async def force_screenshot(self, path: str) -> None:
        """Capture a screenshot that ignores FLAG_SECURE via Yadb."""
        await self._ensure_yadb()
        await self._run_adb_command([
            "-s", self.device_id, "shell",
            "app_process",
            f"-Djava.class.path={YADB_DEVICE_PATH}",
            YADB_DEVICE_PATH,
            "com.ysbing.yadb.Main",
            "-screenshot",
            path,
        ])

    async def screenshot_base64(self) -> str:
        """Capture the current frame as base64 (upstream screenshotBase64)."""
        return await self._take_screenshot()

    async def get_display_density(self) -> int:
        """Display density (upstream getDisplayDensity, default 160)."""
        return await self._get_screen_density()

    async def get_display_orientation(self) -> int:
        """Surface orientation 0..3 (upstream getDisplayOrientation)."""
        try:
            result = await self._run_adb_command(
                ["-s", self.device_id, "shell", "dumpsys", "input"],
                capture_output=True,
            )
            match = re.search(
                r"SurfaceOrientation:\s*(\d)",
                result.stdout.decode("utf-8", errors="ignore"),
            )
            if match:
                return int(match.group(1))
        except Exception as e:  # noqa: BLE001 - falls back to display dump
            logger.debug(f"Failed to get orientation from input: {e}")

        try:
            result = await self._run_adb_command(
                ["-s", self.device_id, "shell", "dumpsys", "display"],
                capture_output=True,
            )
            match = re.search(
                r"mCurrentOrientation=(\d)",
                result.stdout.decode("utf-8", errors="ignore"),
            )
            if match:
                return int(match.group(1))
        except Exception as e:  # noqa: BLE001 - default below
            logger.debug(f"Failed to get orientation from display: {e}")
        return 0

    async def get_elements_info(self) -> List[Any]:
        """Element list is not extracted on Android (upstream returns [])."""
        return []

    async def get_elements_node_tree(self) -> Dict[str, Any]:
        """Simplified empty node tree (upstream)."""
        return {"node": None, "children": []}

    async def get_screen_size(self) -> Dict[str, int]:
        """Logical screen size as ``{width, height}`` (upstream)."""
        return await self.size()

    async def get_ui_tree(self) -> UITree:
        """Current UI tree snapshot (upstream getUITree)."""
        return await self._build_ui_tree()

    async def launch(self, uri: str) -> 'AndroidDevice':
        """Launch a URI, app name or package and return this device."""
        await self.launch_app(uri)
        return self

    async def terminate(self, uri: str) -> None:
        """Force-stop an app by package name (upstream terminate)."""
        await self.stop_app(uri)

    async def url(self) -> str:
        """Current page URL is unavailable on Android (upstream returns '')."""
        return ""

    async def _scroll_in_content_direction(
        self,
        direction: str,
        distance: Optional[int] = None,
        start_point: Optional[Sequence[float]] = None,
    ) -> None:
        """Scroll `direction` (content direction) with upstream defaults."""
        if distance is None and start_point is None:
            if not self._screen_size:
                await self._get_screen_size()
            (from_x, from_y), (to_x, to_y) = resolve_default_mobile_scroll(
                direction,
                {
                    "width": self._screen_size.width,
                    "height": self._screen_size.height,
                },
            )
            await self.swipe(
                from_x, from_y, to_x, to_y,
                duration=DEFAULT_NORMAL_SCROLL_DURATION,
            )
            return
        # The finger travels opposite to the content direction.
        await self._swipe_direction(
            _SCROLL_DIRECTION_FOR_SWIPE[direction],
            distance,
            point=start_point,
        )

    async def scroll_up(
        self,
        distance: Optional[int] = None,
        start_point: Optional[Sequence[float]] = None,
    ) -> None:
        await self._scroll_in_content_direction("up", distance, start_point)

    async def scroll_down(
        self,
        distance: Optional[int] = None,
        start_point: Optional[Sequence[float]] = None,
    ) -> None:
        await self._scroll_in_content_direction("down", distance, start_point)

    async def scroll_left(
        self,
        distance: Optional[int] = None,
        start_point: Optional[Sequence[float]] = None,
    ) -> None:
        await self._scroll_in_content_direction("left", distance, start_point)

    async def scroll_right(
        self,
        distance: Optional[int] = None,
        start_point: Optional[Sequence[float]] = None,
    ) -> None:
        await self._scroll_in_content_direction("right", distance, start_point)

    async def scroll_until_top(
        self, start_point: Optional[Sequence[float]] = None
    ) -> None:
        await self.scroll("up", point=start_point, scroll_type="scrollToTop")

    async def scroll_until_bottom(
        self, start_point: Optional[Sequence[float]] = None
    ) -> None:
        await self.scroll("down", point=start_point, scroll_type="scrollToBottom")

    async def scroll_until_left(
        self, start_point: Optional[Sequence[float]] = None
    ) -> None:
        await self.scroll("left", point=start_point, scroll_type="scrollToLeft")

    async def scroll_until_right(
        self, start_point: Optional[Sequence[float]] = None
    ) -> None:
        await self.scroll("right", point=start_point, scroll_type="scrollToRight")

    async def get_context(self) -> UIContext:
        """Get current UI context"""
        try:
            # Take screenshot
            screenshot_base64 = await self._take_screenshot()
            
            # Get UI dump
            ui_elements = await self._get_ui_elements()
            
            # Build UI tree
            tree = await self._build_ui_tree()
            
            return UIContext(
                screenshot_base64=screenshot_base64,
                size=self._screen_size or Size(width=1080, height=1920),
                content=ui_elements,
                tree=tree
            )
            
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            raise
    
    async def action_space(self) -> List[str]:
        """Get available actions"""
        return [
            "tap", "long_press", "swipe", "scroll",
            "input", "clear", "back", "home", "recent",
            "volume_up", "volume_down", "power",
            "install_app", "launch_app", "stop_app"
        ]
    
    async def tap(self, x: float, y: float) -> None:
        """Tap at logical coordinates (converted to physical for adb)."""
        try:
            px, py = self._to_physical(x, y)
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "tap", str(px), str(py)
            ])
        except Exception as e:
            logger.error(f"Failed to tap at ({x}, {y}): {e}")
            raise

    def _to_physical(self, x: float, y: float) -> tuple[int, int]:
        """Logical (AI) coordinates -> physical adb coordinates.

        Android reports physical pixels while the screenshot/size pair exposed
        to the model is logical (upstream adjustCoordinates).
        """
        if not self._physical_size or not self._screen_size:
            return int(round(x)), int(round(y))
        scale_x = self._physical_size.width / self._screen_size.width
        scale_y = self._physical_size.height / self._screen_size.height
        return int(round(x * scale_x)), int(round(y * scale_y))
    
    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        """Long press at coordinates"""
        try:
            px, py = self._to_physical(x, y)
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe", 
                str(px), str(py), str(px), str(py), str(duration)
            ])
        except Exception as e:
            logger.error(f"Failed to long press at ({x}, {y}): {e}")
            raise
    
    async def swipe(
        self,
        direction_or_start_x,
        start_y=None,
        end_x=None,
        end_y=None,
        duration: int = 300,
        distance: Optional[int] = None,
    ) -> None:
        """Swipe.

        Two forms:
        - swipe(direction, distance=...) : finger-movement direction swipe
          ('up' | 'down' | 'left' | 'right'), used by the action space.
        - swipe(start_x, start_y, end_x, end_y, duration) : coordinate swipe.
        """
        try:
            if isinstance(direction_or_start_x, str):
                await self._swipe_direction(
                    direction_or_start_x, distance, duration=duration
                )
                return
            start_x = direction_or_start_x
            fx, fy = self._to_physical(start_x, start_y)
            tx, ty = self._to_physical(end_x, end_y)
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "swipe",
                str(fx), str(fy), str(tx), str(ty), str(duration)
            ])
        except Exception as e:
            logger.error(f"Failed to swipe: {e}")
            raise

    async def swipe_points(
        self,
        start: Sequence[float],
        end: Sequence[float],
        duration: Optional[int] = None,
    ) -> None:
        """Endpoint swipe between two logical points (upstream swipe(start, end))."""
        await self.swipe(
            start[0], start[1], end[0], end[1],
            duration=int(duration if duration is not None else 300),
        )

    async def size(self) -> Dict[str, int]:
        """Logical screen size (upstream size()); physical / display density.

        When scrcpy is opted in and connected, its video resolution is the
        frame coordinate space and takes precedence.
        """
        adapter = self._scrcpy_adapter
        if adapter is not None and adapter.is_enabled():
            scrcpy_size = adapter.get_size()
            if scrcpy_size is not None:
                return scrcpy_size
        if not self._screen_size:
            await self._get_screen_size()
        return {"width": self._screen_size.width, "height": self._screen_size.height}

    async def pull_gesture(
        self,
        direction: str,
        start_point: Optional[Sequence[float]] = None,
        distance: Optional[int] = None,
        duration: Optional[int] = None,
    ) -> None:
        """Pull to refresh (down) or load more (up), upstream PullGesture.

        Defaults: pull down starts at 15% of the screen height and travels
        half of it; pull up starts at 85% and travels 40%.
        """
        if direction not in ("up", "down"):
            raise ValueError(f"Unknown pull direction: {direction}")
        if not self._screen_size:
            await self._get_screen_size()
        width, height = self._screen_size.width, self._screen_size.height
        if start_point:
            start_x = _round_half_up(start_point[0])
            start_y = _round_half_up(start_point[1])
        else:
            start_x = _round_half_up(width / 2)
            start_y = _round_half_up(
                height * (0.15 if direction == "down" else 0.85)
            )
        if direction == "down":
            pull_distance = _round_half_up(distance or height * 0.5)
            duration_ms = int(duration if duration is not None else 800)
            end_y = start_y + pull_distance
        else:
            pull_distance = _round_half_up(distance or height * 0.4)
            duration_ms = int(duration if duration is not None else 600)
            end_y = start_y - pull_distance
        await self.swipe(start_x, start_y, start_x, end_y, duration=duration_ms)
        await asyncio.sleep(0.2 if direction == "down" else 0.1)

    async def pinch(
        self,
        center: List[float],
        start_distance: float,
        end_distance: float,
        duration: Optional[int] = None,
    ) -> None:
        """Two-finger pinch through yadb (upstream Android touch.pinch).

        yadb only injects gestures into the default display, so fail fast on
        other displays instead of silently pinching the main screen.
        """
        if self.config.display_id != 0:
            raise RuntimeError(
                "Pinch is not supported on a non-default display "
                f"(displayId={self.config.display_id}). The underlying yadb "
                "tool only injects gestures into the default display."
            )
        await self._ensure_yadb()
        center_x, center_y = self._to_physical(center[0], center[1])
        ratio = center_x / center[0] if center_x != 0 and center[0] != 0 else 1
        duration_ms = int(duration if duration is not None else 500)
        await self._run_adb_command([
            "-s", self.device_id, "shell",
            "app_process",
            f"-Djava.class.path={YADB_DEVICE_PATH}",
            YADB_DEVICE_PATH,
            "com.ysbing.yadb.Main",
            "-pinch",
            str(center_x),
            str(center_y),
            str(_round_half_up(start_distance * ratio)),
            str(_round_half_up(end_distance * ratio)),
            str(duration_ms),
        ])

    async def _swipe_direction(
        self,
        direction: str,
        distance: Optional[int] = None,
        point: Optional[Sequence[float]] = None,
        duration: int = DEFAULT_NORMAL_SCROLL_DURATION,
    ) -> None:
        if not self._screen_size:
            await self._get_screen_size()
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid swipe direction: {direction}")

        width, height = self._screen_size.width, self._screen_size.height
        horizontal = direction in ("left", "right")
        forward = direction in ("down", "right")
        axis_size = width if horizontal else height
        center_x, center_y = width // 2, height // 2
        start: Tuple[int, int]
        end: Tuple[int, int]

        if distance is None and point is None:
            # Upstream scrollDefault: the finger crosses the central 70% slowly
            # enough to keep the release velocity low.
            start, end = resolve_default_mobile_scroll(
                direction, {"width": width, "height": height}
            )
            duration = DEFAULT_NORMAL_SCROLL_DURATION
        elif point is not None:
            # Anchored gesture: start where the model pointed and travel toward
            # the edge in the requested direction.
            start = (_round_half_up(point[0]), _round_half_up(point[1]))
            # Upstream uses `distance || height`; a zero request means the axis.
            scroll_distance = _round_half_up(distance or axis_size)
            delta_x = scroll_distance if direction == "right" else (
                -scroll_distance if direction == "left" else 0
            )
            delta_y = scroll_distance if direction == "down" else (
                -scroll_distance if direction == "up" else 0
            )
            end = calculate_scroll_end_point(start, delta_x, delta_y, width, height)
            if distance is not None:
                applied = (
                    abs(end[0] - start[0]) if horizontal else abs(end[1] - start[1])
                )
                warn_scroll_distance_clamped(
                    _SCROLL_DIRECTION_FOR_SWIPE[direction], scroll_distance, applied
                )
        else:
            # Upstream scrollRaw: start at a quarter of the axis so a single
            # explicit-distance gesture keeps (n-1)/n of the screen as travel.
            scroll_distance = _round_half_up(distance or axis_size)
            start_axis = _round_half_up(
                axis_size / 4 if forward else axis_size * 3 / 4
            )
            end_axis = (
                start_axis + scroll_distance
                if forward
                else start_axis - scroll_distance
            )
            end_axis = min(max(end_axis, 0), axis_size)
            if horizontal:
                start, end = (start_axis, center_y), (end_axis, center_y)
            else:
                start, end = (center_x, start_axis), (center_x, end_axis)

        fx, fy = self._to_physical(*start)
        tx, ty = self._to_physical(*end)
        await self._run_adb_command([
            "-s", self.device_id, "shell", "input", "swipe",
            str(fx), str(fy), str(tx), str(ty), str(duration),
        ])

    async def drag_and_drop(self, from_point, to_point, duration: int = 1000) -> None:
        """Drag an element from one point to another (upstream dragPoint)."""
        try:
            from_x, from_y = from_point
            to_x, to_y = to_point
            await self.swipe(
                from_x, from_y, to_x, to_y, duration=duration
            )
        except Exception as e:
            logger.error(f"Failed to drag from {from_point} to {to_point}: {e}")
            raise

    async def input_text(self, text: str) -> None:
        r"""Input text.

        Uses the upstream IME strategy (MIDSCENE_ANDROID_IME_STRATEGY):
        'yadb-for-non-ascii' (default) routes text that `adb shell input text`
        cannot deliver reliably (non-ASCII, % specifiers, \ ` $, mixed quotes)
        through the Yadb tool; 'always-yadb' always uses Yadb; 'legacy' always
        uses `input text` with proper shell escaping.
        """
        await self._type_text(text)

    async def _type_text(self, text: str) -> None:
        """Type text following the resolved IME strategy (upstream typeText)."""
        if not text:
            return
        import os as _os

        strategy = (
            _os.environ.get("MIDSCENE_ANDROID_IME_STRATEGY")
            or IME_STRATEGY_YADB_FOR_NON_ASCII
        )
        if strategy not in (
            IME_STRATEGY_ALWAYS_YADB,
            IME_STRATEGY_YADB_FOR_NON_ASCII,
            IME_STRATEGY_LEGACY,
        ):
            logger.warning(
                f"Unknown MIDSCENE_ANDROID_IME_STRATEGY {strategy!r}, "
                f"falling back to {IME_STRATEGY_YADB_FOR_NON_ASCII}"
            )
            strategy = IME_STRATEGY_YADB_FOR_NON_ASCII

        needs_yadb = strategy == IME_STRATEGY_ALWAYS_YADB or (
            strategy == IME_STRATEGY_YADB_FOR_NON_ASCII
            and should_use_yadb_for_text(text)
        )

        try:
            if needs_yadb:
                await self._exec_yadb_raw(text)
            else:
                await self._shell_input_text(text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise

    async def _shell_input_text(self, text: str) -> None:
        """`adb shell input text` with proper shell escaping; input text cannot
        handle newlines, so segments are split and Enter is pressed between
        them (upstream shellInputText)."""
        segments = text.split("\n")
        for index, segment in enumerate(segments):
            if segment:
                await self._run_adb_command([
                    "-s", self.device_id, "shell",
                    "input", "text", shell_escape_arg(segment),
                ])
            if index < len(segments) - 1:
                await self.key_event("KEYCODE_ENTER")

    def _resolve_yadb_bin_path(self) -> str:
        """Local Yadb binary path: <MIDSCENE_RUN_DIR>/bin/yadb."""
        from midscene.shared.env import get_midscene_run_dir

        if self._yadb_bin_path is None:
            self._yadb_bin_path = str(
                Path(get_midscene_run_dir("bin")) / "yadb"
            )
        return self._yadb_bin_path

    async def _ensure_yadb(self) -> None:
        """Download (once) and push the Yadb tool to the device."""
        if self._yadb_pushed:
            return
        bin_path = Path(self._resolve_yadb_bin_path())
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        if not bin_path.exists():
            import httpx

            url = (
                "https://github.com/ysbing/YADB/releases/download/"
                f"{YADB_VERSION}/yadb"
            )
            logger.info(f"Downloading Yadb tool from {url} ...")
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                response = await client.get(url)
            if response.status_code != 200:
                raise RuntimeError(
                    f"Failed to download Yadb tool ({response.status_code}). "
                    "Chinese/special-character input requires Yadb; place the "
                    "binary at " + str(bin_path) + " manually, or set "
                    "MIDSCENE_ANDROID_IME_STRATEGY=legacy."
                )
            bin_path.write_bytes(response.content)
            bin_path.chmod(0o755)
        await self._run_adb_command(["push", str(bin_path), YADB_DEVICE_PATH])
        self._yadb_pushed = True

    async def _exec_yadb_raw(self, keyboard_content: str) -> None:
        """Inject text through the Yadb app_process tool."""
        try:
            await self._ensure_yadb()
        except Exception as e:
            logger.warning(
                f"Yadb unavailable ({e}); falling back to `input text`."
            )
            await self._shell_input_text(keyboard_content)
            return
        await self._run_adb_command([
            "-s", self.device_id, "shell",
            "app_process",
            f"-Djava.class.path={YADB_DEVICE_PATH}",
            YADB_DEVICE_PATH,
            "com.ysbing.yadb.Main",
            "-keyboard",
            "'" + escape_for_shell(keyboard_content) + "'",
        ])

    async def run_adb_shell(self, command: str, timeout: Optional[float] = None) -> str:
        """Run an arbitrary adb shell command (RunAdbShell action).

        `timeout` is accepted for upstream compatibility; the underlying adb
        client applies its own command timeout.
        """
        output = await self._run_adb_command(["-s", self.device_id, "shell", command])
        return output if isinstance(output, str) else ""
    
    async def clear_text(self) -> None:
        """Clear text in focused field"""
        try:
            # Select all and delete
            await self.key_event("KEYCODE_MOVE_END")
            await self.key_event("KEYCODE_SHIFT_LEFT")
            await self.key_event("KEYCODE_MOVE_HOME")
            await self.key_event("KEYCODE_DEL")
        except Exception as e:
            logger.error(f"Failed to clear text: {e}")
            raise
    
    async def scroll(
        self,
        direction: str,
        distance: Optional[int] = None,
        point: Optional[Sequence[float]] = None,
        scroll_type: Optional[str] = None,
    ) -> None:
        """Scroll in direction.

        `point` is the gesture origin (usually a located region) and the
        gesture travels toward the matching screen edge. Scroll directions
        describe the content to reveal, i.e. the opposite of the finger
        movement used by swipe.
        """
        try:
            finger_direction = {
                "down": "up",
                "up": "down",
                "left": "right",
                "right": "left",
            }.get(direction)
            if finger_direction is None:
                raise ValueError(f"Invalid scroll direction: {direction}")

            if (scroll_type or "").startswith("scrollTo"):
                # Upstream scrollUntil*: repeated fast gestures anchored from
                # the located point to the target screen edge, then a 1s
                # settle window before the next observation.
                if not self._screen_size:
                    await self._get_screen_size()
                width = self._screen_size.width
                height = self._screen_size.height
                if point is not None:
                    start = (_round_half_up(point[0]), _round_half_up(point[1]))
                    end = {
                        "up": (start[0], height),
                        "down": (start[0], 0),
                        "left": (width, start[1]),
                        "right": (0, start[1]),
                    }[direction]
                    for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                        await self.swipe(
                            start[0], start[1], end[0], end[1],
                            duration=DEFAULT_FAST_SCROLL_DURATION,
                        )
                else:
                    for _ in range(DEFAULT_SCROLL_UNTIL_TIMES):
                        await self._swipe_direction(
                            finger_direction,
                            distance=9999999,
                            duration=DEFAULT_FAST_SCROLL_DURATION,
                        )
                await asyncio.sleep(1)
                return

            await self._swipe_direction(finger_direction, distance, point=point)

        except Exception as e:
            logger.error(f"Failed to scroll {direction}: {e}")
            raise

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret left/right with DPAD arrow key events (upstream)."""
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.keyboard_press(arrow_key)

    async def get_device_time(self) -> str:
        """Device wall clock as HH:MM:SS (upstream useDeviceTime)."""
        result = await self._run_adb_command(
            ["-s", self.device_id, "shell", "date", "+%H:%M:%S"],
            capture_output=True,
        )
        return result.stdout.decode("utf-8").strip()
    
    async def clear_input(self, element: Any = None) -> None:
        """Clear text in the focused field, optionally focusing ``element`` first."""
        if element is not None:
            center = element.center
            await self.tap(center[0], center[1])
        await self.clear_text()

    async def replace_input(self, text: str) -> None:
        """Replace the content of the focused field"""
        await self.clear_text()
        await self.input_text(text)

    async def keyboard_press(self, key: str) -> None:
        """Press a key by name, e.g. 'Enter', 'Tab', 'Backspace', 'Control+A'."""
        key_map = {
            "ENTER": "KEYCODE_ENTER",
            "TAB": "KEYCODE_TAB",
            "BACKSPACE": "KEYCODE_DEL",
            "DELETE": "KEYCODE_FORWARD_DEL",
            "ESCAPE": "KEYCODE_ESCAPE",
            "HOME": "KEYCODE_HOME",
            "ARROWUP": "KEYCODE_DPAD_UP",
            "ARROWDOWN": "KEYCODE_DPAD_DOWN",
            "ARROWLEFT": "KEYCODE_DPAD_LEFT",
            "ARROWRIGHT": "KEYCODE_DPAD_RIGHT",
        }
        # combinations like 'Control+A' fall back to the bare key
        bare_key = key.split("+")[-1].upper()
        key_code = key_map.get(bare_key)
        if key_code:
            await self.key_event(key_code)
        elif bare_key.isalnum() and len(bare_key) == 1:
            await self.key_event(f"KEYCODE_{bare_key.upper()}")
        else:
            raise ValueError(f"Unsupported key for Android: {key}")

    async def key_event(self, key_code: str) -> None:
        """Send key event"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "shell", "input", "keyevent", key_code
            ])
        except Exception as e:
            logger.error(f"Failed to send key event {key_code}: {e}")
            raise
    
    async def back(self) -> None:
        """Press back button"""
        await self.key_event("KEYCODE_BACK")
    
    async def home(self) -> None:
        """Press home button"""
        await self.key_event("KEYCODE_HOME")
    
    async def recent(self) -> None:
        """Press recent apps button"""
        await self.key_event("KEYCODE_APP_SWITCH")
    
    async def install_app(self, apk_path: str) -> None:
        """Install APK"""
        try:
            await self._run_adb_command([
                "-s", self.device_id, "install", apk_path
            ])
        except Exception as e:
            logger.error(f"Failed to install app: {e}")
            raise
    
    def set_app_name_mapping(self, mapping: Dict[str, str]) -> None:
        """Set the friendly app name -> package name mapping (upstream
        setAppNameMapping)."""
        self._app_name_mapping = merge_and_normalize_app_name_mapping({}, mapping)

    def _resolve_package_name(self, app_name: str) -> Optional[str]:
        """Resolve a friendly app name to its package name, if mapped."""
        return self._app_name_mapping.get(normalize_for_comparison(app_name))

    async def launch_app(self, package_name: str, activity: Optional[str] = None) -> None:
        """Launch an app.

        Accepts a friendly app name, a package name, ``package/activity`` or a
        URI with a scheme, matching upstream ``launch(uri)``.
        """
        try:
            if activity:
                component = f"{package_name}/{activity}"
                await self._run_adb_command([
                    "-s", self.device_id, "shell", "am", "start", "-n", component
                ])
                return
            resolved = self._resolve_package_name(package_name) or package_name
            if "://" in resolved:
                await self._run_adb_command([
                    "-s", self.device_id, "shell", "am", "start",
                    "-a", "android.intent.action.VIEW", "-d", resolved,
                ])
            elif "/" in resolved:
                await self._run_adb_command([
                    "-s", self.device_id, "shell", "am", "start", "-n", resolved
                ])
            else:
                await self._run_adb_command([
                    "-s", self.device_id, "shell", "monkey",
                    "-p", resolved, "-c", "android.intent.category.LAUNCHER", "1",
                ])
        except Exception as e:
            logger.error(f"Failed to launch app: {e}")
            raise
    
    async def stop_app(self, package_name: str) -> None:
        """Stop app"""
        try:
            package_part = package_name.split("/", 1)[0]
            resolved = self._resolve_package_name(package_part) or package_part
            await self._run_adb_command([
                "-s", self.device_id, "shell", "am", "force-stop", resolved
            ])
        except Exception as e:
            logger.error(f"Failed to stop app: {e}")
            raise
    
    async def _take_screenshot(self) -> str:
        """Take screenshot and return base64 string.

        Opt-in scrcpy is tried first; any failure logs a diagnostic and falls
        through to the unchanged ADB screencap path.
        """
        adapter = self._scrcpy_adapter
        if adapter is not None and adapter.is_enabled():
            try:
                data_url = await adapter.screenshot_base64()
                return (
                    data_url.split(",", 1)[1]
                    if data_url.startswith("data:")
                    else data_url
                )
            except Exception as e:
                logger.warning(
                    "Scrcpy screenshot failed, falling back to standard ADB "
                    f"method: {e}"
                )

        try:
            # Take screenshot using screencap
            result = await self._run_adb_command([
                "-s", self.device_id, "shell", "screencap", "-p"
            ], capture_output=True)
            
            # Convert bytes to base64
            screenshot_base64 = base64.b64encode(result.stdout).decode('utf-8')
            
            return screenshot_base64
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise
    
    async def _get_ui_elements(self) -> List[AndroidElement]:
        """Get UI elements using uiautomator dump"""
        try:
            xml_content = await capture_android_ui_tree(
                self._run_adb_command, self.device_id
            )

            return [
                AndroidElement(
                    device=self,
                    id=f"element_{index}",
                    **descriptor,
                )
                for index, descriptor in enumerate(
                    parse_ui_automator_xml(xml_content)
                )
            ]
            
        except Exception as e:
            logger.error(f"Failed to get UI elements: {e}")
            return []
    
    async def _build_ui_tree(self) -> UITree:
        """Build UI tree structure"""
        # Simplified implementation - return minimal tree
        root_node = UINode(
            id="root",
            content="",
            rect=Rect(left=0, top=0, width=self._screen_size.width if self._screen_size else 1080, 
                     height=self._screen_size.height if self._screen_size else 1920),
            center=(540, 960),
            node_type=NodeType.CONTAINER,
            attributes={},
            is_visible=True,
            children=[]
        )
        
        return UITree(node=root_node, children=[])
    
    async def _get_screen_size(self) -> None:
        """Resolve physical size + display density.

        Upstream `size()` returns logical pixels: physical / (density / 160).
        Gestures convert back with `_to_physical`.
        """
        try:
            result = await self._run_adb_command([
                "-s", self.device_id, "shell", "wm", "size"
            ], capture_output=True)

            output = result.stdout.decode('utf-8').strip()
            physical = parse_screen_size_output(output)
            if physical is None:
                physical = Size(width=1080, height=1920)

            density = await self._get_screen_density()
            self._device_pixel_ratio = density / 160 if density else 1.0
            self._physical_size = physical
            self._screen_size = Size(
                width=max(1, round(physical.width / self._device_pixel_ratio)),
                height=max(1, round(physical.height / self._device_pixel_ratio)),
            )

        except Exception as e:
            logger.warning(f"Failed to get screen size: {e}")
            self._physical_size = Size(width=1080, height=1920)
            self._screen_size = Size(width=1080, height=1920)
            self._device_pixel_ratio = 1.0

    async def _get_screen_density(self) -> int:
        """Display density (upstream getDisplayDensity, default 160)."""
        try:
            result = await self._run_adb_command(
                ["-s", self.device_id, "shell", "wm", "density"],
                capture_output=True,
            )
            text = result.stdout.decode("utf-8", errors="ignore")
            return parse_screen_density(text)
        except Exception as e:
            logger.debug(f"Failed to read display density: {e}")
        return 160
    
    async def _setup_ime(self) -> None:
        """No IME setup required: text injection uses the Yadb tool
        (app_process) or `input text`, neither of which needs an IME."""
        try:
            pass
        except Exception as e:
            logger.warning(f"Failed to setup IME: {e}")
    
    @staticmethod
    async def _run_adb_command(
        args: List[str], 
        capture_output: bool = False,
        timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """Run one ADB command through the adb helper module."""
        return await run_adb_command(
            args, capture_output=capture_output, timeout=timeout
        )
    
    async def disconnect(self) -> None:
        """Disconnect from device"""
        if self._scrcpy_adapter is not None:
            try:
                await self._scrcpy_adapter.disconnect()
            except Exception as e:
                logger.debug(f"Error disconnecting scrcpy: {e}")
            self._scrcpy_adapter = None
        self._connected = False
        logger.info(f"Disconnected from device: {self.device_id}")
    
    def __del__(self):
        """Cleanup on deletion"""
        if self._connected:
            # Note: Can't use async in __del__, this is just for cleanup tracking
            logger.debug(f"Device {self.device_id} being garbage collected")