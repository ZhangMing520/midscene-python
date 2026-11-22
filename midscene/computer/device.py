"""Computer (desktop) automation device (Windows / macOS / Linux).

Synced from upstream packages/computer/src. The device captures the full
screen; pointer/keyboard handling lives in ``input_driver.py`` (upstream
input-driver.ts) and is backed by pyautogui. Text input is pasted through the
clipboard by default (upstream typeViaClipboard) so CJK text and IME
interference are handled the same way as upstream.
"""

import asyncio
import base64
import io
import json
import math
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.computer.input_driver import (
    ComputerInputDriver,
    load_pyautogui as _pyautogui,
    normalize_key as _normalize_key_impl,
)
from midscene.computer.utils import is_mac as _is_mac
from midscene.computer.xvfb import (
    check_xvfb_installed,
    needs_xvfb,
    start_xvfb,
)
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

# libnut fallback scroll tuning shared with input_driver.upstream constants.
_EDGE_SCROLL_TOTAL_PX = 50_000
_LIBNUT_FALLBACK_PIXELS_PER_DETENT = 100
_LIBNUT_FALLBACK_MAX_DETENTS = 200
_LIBNUT_FALLBACK_DETENT_AMOUNT = 120 if platform.system() == "Windows" else 1

# Exported for regression coverage (upstream LIBNUT_FALLBACK_EDGE_DETENTS).
LIBNUT_FALLBACK_EDGE_DETENTS = min(
    _LIBNUT_FALLBACK_MAX_DETENTS,
    max(
        1,
        math.ceil(_EDGE_SCROLL_TOTAL_PX / _LIBNUT_FALLBACK_PIXELS_PER_DETENT),
    ),
)

_phased_scroll_binary_path: Any = None
_display_info_binary_path: Any = None
_phased_scroll_exec_warned = False


def _binary_candidates(file_name: str) -> List[Path]:
    """Locations where the packaged macOS helper binaries may live."""
    here = Path(__file__).resolve()
    package_root = here.parent.parent  # midscene/
    repo_root = package_root.parent
    return [
        repo_root / "bin" / "darwin" / file_name,
        package_root / "bin" / "darwin" / file_name,
        package_root / "computer" / "bin" / "darwin" / file_name,
    ]


def get_phased_scroll_binary() -> Optional[str]:
    """Resolve the bundled macOS phased-scroll helper binary."""
    global _phased_scroll_binary_path
    if _phased_scroll_binary_path is not None:
        return _phased_scroll_binary_path
    if platform.system() != "Darwin":
        _phased_scroll_binary_path = None
        return None
    for candidate in _binary_candidates("phased-scroll"):
        if not candidate.exists():
            continue
        try:
            mode = candidate.stat().st_mode
            if mode & 0o111 == 0:
                candidate.chmod(0o755)
        except OSError as error:
            logger.debug(f"phased-scroll: chmod self-heal failed: {error}")
        _phased_scroll_binary_path = str(candidate)
        return _phased_scroll_binary_path
    logger.debug("phased-scroll binary not found")
    _phased_scroll_binary_path = None
    return None


def get_display_info_binary() -> Optional[str]:
    """Resolve the bundled macOS display-info helper binary."""
    global _display_info_binary_path
    if _display_info_binary_path is not None:
        return _display_info_binary_path
    if platform.system() != "Darwin":
        _display_info_binary_path = None
        return None
    for candidate in _binary_candidates("display-info"):
        if candidate.exists():
            _display_info_binary_path = str(candidate)
            return _display_info_binary_path
    logger.debug("display-info binary not found")
    _display_info_binary_path = None
    return None


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_darwin_display_geometry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    bounds = value.get("bounds")
    return (
        isinstance(value.get("screenIndex"), int)
        and isinstance(value.get("cgDisplayId"), int)
        and isinstance(value.get("primary"), bool)
        and isinstance(bounds, dict)
        and _is_finite_number(bounds.get("x"))
        and _is_finite_number(bounds.get("y"))
        and _is_finite_number(bounds.get("width"))
        and _is_finite_number(bounds.get("height"))
    )


def read_darwin_display_geometries() -> List[Dict[str, Any]]:
    """Read native display geometry from the bundled display-info helper."""
    binary = get_display_info_binary()
    if not binary:
        return []
    try:
        output = subprocess.run(
            [binary],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        ).stdout
        parsed = json.loads(output)
        displays = parsed.get("displays")
        if not isinstance(displays, list):
            return []
        return [
            display
            for display in displays
            if _is_darwin_display_geometry(display)
        ]
    except (OSError, ValueError) as error:
        logger.debug(f"display-info helper failed: {error}")
        return []


def resolve_darwin_display_geometry_from_list(
    display_id: Optional[str], displays: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Resolve a screenshot display id against Darwin display geometry."""
    if not displays:
        return None
    if display_id is None or display_id == "":
        for display in displays:
            if display.get("primary"):
                return display
        for display in displays:
            if display.get("screenIndex") == 0:
                return display
        return displays[0]

    try:
        screen_index = float(display_id)
    except (TypeError, ValueError):
        logger.debug(f"Invalid macOS display id for display geometry: {display_id}")
        return None
    if not math.isfinite(screen_index) or screen_index != int(screen_index):
        logger.debug(f"Invalid macOS display id for display geometry: {display_id}")
        return None
    if screen_index < 0:
        logger.debug(f"Invalid macOS display id for display geometry: {display_id}")
        return None
    index = int(screen_index)
    for display in displays:
        if display.get("screenIndex") == index:
            return display
    for display in displays:
        if display.get("cgDisplayId") == index:
            return display
    return None


def map_display_local_point_to_global(
    point: Dict[str, float], geometry: Optional[Dict[str, Any]] = None
) -> Dict[str, float]:
    """Translate display-local coordinates into global desktop coordinates."""
    if not geometry:
        return point
    bounds = geometry.get("bounds") or {}
    return {
        "x": point["x"] + bounds.get("x", 0),
        "y": point["y"] + bounds.get("y", 0),
    }


def run_phased_scroll(direction: str, pixels: float, steps: int) -> bool:
    """Run the macOS phased-scroll helper; False when unavailable or failed."""
    global _phased_scroll_exec_warned
    binary = get_phased_scroll_binary()
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, direction, str(max(1, round(pixels))), str(steps)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return True
        if not _phased_scroll_exec_warned:
            _phased_scroll_exec_warned = True
            logger.warning(
                "[@midscene/computer] phased-scroll helper failed "
                f"(exit={result.returncode}); falling back to keyboard/libnut."
            )
        return False
    except OSError as error:
        if not _phased_scroll_exec_warned:
            _phased_scroll_exec_warned = True
            logger.warning(
                "[@midscene/computer] phased-scroll helper failed to spawn "
                f"({error}); falling back to keyboard/libnut."
            )
        return False


def _normalize_key(key: str) -> str:
    return _normalize_key_impl(key, _is_mac)


class ComputerDevice(AbstractInterface):
    """Local computer device: full-screen capture + OS-level input."""

    # TODO(computer): multi-display capture needs a per-monitor screenshot
    # backend (upstream listDisplays); pyautogui only grabs the main display.
    def __init__(
        self,
        display_id: Optional[str] = None,
        keyboard_modifier_delay: int = 0,
        headless: bool = False,
    ):
        if display_id is not None:
            # Upstream's computer env carries displayId; refuse to pretend the
            # pyautogui backend can select a display.
            raise NotImplementedError(
                "desktop capture uses the primary display only, "
                f"got display_id={display_id!r}"
            )
        self.keyboard_modifier_delay = keyboard_modifier_delay
        self._input = ComputerInputDriver(
            is_mac=lambda: _is_mac(),
            keyboard_modifier_delay=keyboard_modifier_delay,
        )
        self._xvfb = None
        self._previous_display: Optional[str] = None
        self._description: Optional[str] = None
        self._destroyed = False
        if needs_xvfb(headless) and not os.environ.get("DISPLAY"):
            if not check_xvfb_installed():
                raise RuntimeError(
                    "headless computer automation requires Xvfb; install it "
                    "or run with DISPLAY set"
                )
            self._previous_display = os.environ.get("DISPLAY")
            self._xvfb = start_xvfb()
            os.environ["DISPLAY"] = self._xvfb.display

    def close(self) -> None:
        """Stop the Xvfb instance started for headless mode, if any."""
        if self._xvfb is None:
            return
        self._xvfb.stop()
        self._xvfb = None
        if self._previous_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = self._previous_display
        self._previous_display = None

    def describe(self) -> str:
        """Human-readable device description (upstream describe())."""
        return self._description or "Computer Device"

    async def connect(self) -> None:
        """Initialize the desktop backend and record the device description."""
        if self._destroyed:
            raise RuntimeError("ComputerDevice has been destroyed")
        try:
            pyautogui = await _pyautogui()
            screen_size = await asyncio.to_thread(pyautogui.size)
            displays = await self.list_displays()
            display_names = (
                ", ".join(display["name"] for display in displays)
                if displays
                else "Unknown"
            )
            self._description = (
                "\nType: Computer"
                f"\nPlatform: {platform.system().lower()}"
                f"\nDisplay: Primary"
                f"\nScreen Size: {int(screen_size.width)}x"
                f"{int(screen_size.height)}"
                f"\nAvailable Displays: {display_names}\n"
            )
        except Exception as error:
            logger.debug(f"Failed to connect: {error}")
            raise RuntimeError(
                f"Unable to connect to computer device: {error}"
            ) from error

    async def destroy(self) -> None:
        """Release SDK-owned resources (upstream destroy())."""
        if self._destroyed:
            return
        self._destroyed = True
        self.close()
        logger.debug("Computer device destroyed")

    async def screenshot_base64(self) -> str:
        """Capture the primary display as a PNG data URL."""
        if self._destroyed:
            raise RuntimeError("ComputerDevice has been destroyed")
        pyautogui = await _pyautogui()
        screenshot = await asyncio.to_thread(pyautogui.screenshot)
        buffer = io.BytesIO()
        screenshot.save(buffer, format="PNG")
        body = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{body}"

    @staticmethod
    async def list_displays() -> List[Dict[str, Any]]:
        """List available displays; pyautogui exposes the primary one."""
        try:
            pyautogui = await _pyautogui()
            size = await asyncio.to_thread(pyautogui.size)
            return [
                {
                    "id": "0",
                    "name": f"Display 0 ({int(size.width)}x{int(size.height)})",
                    "primary": True,
                }
            ]
        except Exception as error:
            logger.debug(f"Failed to list displays: {error}")
            raise RuntimeError(f"Failed to list displays: {error}") from error

    async def url(self) -> str:
        """Desktop interfaces have no URL (upstream returns an empty string)."""
        return ""

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.COMPUTER

    async def get_context(self) -> UIContext:
        try:
            pyautogui = await _pyautogui()
            screenshot = await asyncio.to_thread(pyautogui.screenshot)
            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")
            screenshot_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

            screen_size = await asyncio.to_thread(pyautogui.size)
            size = Size(width=int(screen_size.width), height=int(screen_size.height))
            return UIContext(
                screenshot_base64=screenshot_base64,
                size=size,
                content=[],
                tree=UITree(
                    node=UINode(
                        id="root",
                        content="",
                        rect=Rect(
                            left=0,
                            top=0,
                            width=size.width,
                            height=size.height,
                        ),
                        center=(size.width / 2, size.height / 2),
                        node_type=NodeType.CONTAINER,
                    )
                ),
            )
        except Exception as e:
            logger.error(f"Failed to capture desktop context: {e}")
            raise

    async def action_space(self) -> List[str]:
        return [
            "tap", "right_click", "middle_click", "double_click", "hover",
            "input", "clear", "key_press", "scroll", "drag", "long_press",
            "swipe",
        ]

    async def tap(self, x: float, y: float) -> None:
        await self._input.tap(x, y)

    async def right_click(self, x: float, y: float) -> None:
        await self._input.right_click(x, y)

    async def middle_click(self, x: float, y: float) -> None:
        await self._input.middle_click(x, y)

    async def double_click(self, x: float, y: float) -> None:
        await self._input.double_click(x, y)

    async def hover(self, x: float, y: float) -> None:
        await self._input.hover(x, y)

    async def input_text(self, text: str) -> None:
        await self._input.input_text(text)

    async def clear_input(self) -> None:
        await self._input.clear_input()

    async def keyboard_press(self, key: str) -> None:
        await self._input.keyboard_press(key)

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        await self._input.cursor_move(direction, times)

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        await self._input.scroll(direction, distance, **kwargs)

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        await self._input.swipe(direction, distance)

    async def swipe_points(
        self,
        start: List[float],
        end: List[float],
        duration: Optional[int] = None,
    ) -> None:
        await self._input.swipe_points(start, end, duration)

    async def size(self) -> Dict[str, int]:
        """Desktop screen size in logical pixels (upstream size())."""
        pyautogui = await _pyautogui()
        screen = await asyncio.to_thread(pyautogui.size)
        return {"width": int(screen.width), "height": int(screen.height)}

    async def drag_and_drop(self, from_point, to_point) -> None:
        await self._input.drag_and_drop(from_point, to_point)

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        await self._input.long_press(x, y, duration)


__all__ = ["ComputerDevice"]
