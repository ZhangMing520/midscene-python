"""Desktop automation device (Windows / macOS / Linux).

Synced from upstream packages/computer/src (v1.17.4). The device captures
the full screen and drives the OS pointer/keyboard through pyautogui; text
input is pasted through the clipboard by default (upstream typeViaClipboard)
so CJK text and IME interference are handled the same way as upstream.
"""

import asyncio
import base64
import io
from typing import List, Optional, Tuple

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


def _import_pyautogui():
    try:
        import pyautogui
    except ImportError as e:
        raise ImportError(
            "Desktop automation needs pyautogui; install the desktop extra "
            "with: pip install midscene-python[desktop]"
        ) from e
    # Drags and swipes end near screen edges, which is exactly where pyautogui
    # raises its FailSafeException.
    pyautogui.FAILSAFE = False
    return pyautogui


async def _pyautogui():
    """Import off the event loop: the first import loads the OS backends."""
    return await asyncio.to_thread(_import_pyautogui)


def _pyperclip():
    try:
        import pyperclip

        return pyperclip
    except ImportError:  # pragma: no cover - optional helper
        return None


# Upstream device.ts keeps `distance` in pixels and converts it for the wheel
# backend, because a wheel unit is not portable: macOS reports pixels per
# event, Linux counts notches and Windows counts WHEEL_DELTA (120) units.
# One notch is billed as ~100px and capped so a bad screen size cannot wedge
# the process.
_PIXELS_PER_DETENT = 100
_MAX_DETENTS = 200
_DETENT_DELAY = 0.03
_EDGE_SCROLL_TOTAL_PX = 50_000
_DEFAULT_SCROLL_VIEWPORT_RATIO = 0.7

# (pyautogui function, sign) per upstream EDGE_SCROLL_SPEC.
_EDGE_SCROLLS = {
    "scrollToTop": ("scroll", 1),
    "scrollToBottom": ("scroll", -1),
    "scrollToLeft": ("hscroll", -1),
    "scrollToRight": ("hscroll", 1),
}


def _detent_count(distance_px: float) -> int:
    """Pixel distance -> wheel notches, at least one and never more than 200."""
    notches = -(-abs(int(distance_px)) // _PIXELS_PER_DETENT)
    return min(_MAX_DETENTS, max(1, notches))


class DesktopDevice(AbstractInterface):
    """Local desktop device: full-screen capture + OS-level input."""

    # TODO(desktop): multi-display capture needs a per-monitor screenshot
    # backend (upstream listDisplays); pyautogui only grabs the main display.
    def __init__(
        self,
        display_id: Optional[str] = None,
        keyboard_modifier_delay: int = 0,
    ):
        if display_id is not None:
            # Upstream's computer env carries displayId; refuse to pretend the
            # pyautogui backend can select a display.
            raise NotImplementedError(
                "desktop capture uses the primary display only, "
                f"got display_id={display_id!r}"
            )
        self.keyboard_modifier_delay = keyboard_modifier_delay

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
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y))

    async def right_click(self, x: float, y: float) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="right")

    async def middle_click(self, x: float, y: float) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="middle")

    async def double_click(self, x: float, y: float) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), clicks=2)

    async def hover(self, x: float, y: float) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))

    async def input_text(self, text: str) -> None:
        """Paste text through the clipboard (upstream typeViaClipboard):
        save old clipboard, write text, simulate Ctrl+V / Cmd+V, restore."""
        if not text:
            return
        pyautogui = await _pyautogui()
        pyperclip = _pyperclip()
        paste_shortcut = ["command", "v"] if _is_mac() else ["ctrl", "v"]

        old_clipboard = None
        if pyperclip is not None:
            try:
                old_clipboard = await asyncio.to_thread(pyperclip.paste)
            except Exception:
                old_clipboard = None
            await asyncio.to_thread(pyperclip.copy, text)
            await asyncio.sleep(0.05)
        elif any(ord(ch) >= 0x80 for ch in text):
            raise RuntimeError(
                "Non-ASCII desktop input requires pyperclip (clipboard paste). "
                "Install it with: pip install pyperclip"
            )

        try:
            if pyperclip is not None:
                await self._press_combo(pyautogui, paste_shortcut)
                await asyncio.sleep(0.1)
            else:
                await asyncio.to_thread(pyautogui.write, text)
        finally:
            if pyperclip is not None and old_clipboard:
                try:
                    await asyncio.to_thread(pyperclip.copy, old_clipboard)
                except Exception:
                    logger.debug("failed to restore clipboard content")

    async def clear_input(self) -> None:
        """Clear the focused field: select all, then backspace (upstream
        selectAllAndDelete)."""
        # Lowercase on purpose: single chars keep their case, and 'A' would add
        # shift and turn the select-all accelerator into something else.
        await self.keyboard_press("Command+a" if _is_mac() else "Control+a")
        await asyncio.sleep(0.05)
        await self.keyboard_press("Backspace")

    async def keyboard_press(self, key: str) -> None:
        pyautogui = await _pyautogui()
        keys = [_normalize_key(part) for part in key.split("+") if part.strip()]
        if not keys:
            raise ValueError(f"Invalid key name: {key!r}")
        for name in keys:
            # An unknown name is a silent no-op in every pyautogui backend, so
            # fail instead of reporting a shortcut that never happened.
            if name not in pyautogui.KEY_NAMES:
                raise ValueError(f"Unknown key name: {name!r}")
        await self._press_combo(pyautogui, keys)

    async def _press_combo(self, pyautogui, keys: List[str]) -> None:
        """Tap the last key with the leading keys held as modifiers.

        `keyboard_modifier_delay` paces the modifier down/up like upstream
        `keyTapWithModifierDelay`; the default 0 uses pyautogui's hotkey.
        """
        if len(keys) == 1:
            await asyncio.to_thread(pyautogui.press, keys[0])
            return

        delay = self.keyboard_modifier_delay / 1000
        if delay <= 0:
            await asyncio.to_thread(pyautogui.hotkey, *keys)
            return

        modifiers, key = keys[:-1], keys[-1]
        for modifier in modifiers:
            await asyncio.to_thread(pyautogui.keyDown, modifier)
            await asyncio.sleep(delay)
        await asyncio.to_thread(pyautogui.press, key)
        for modifier in reversed(modifiers):
            await asyncio.sleep(delay)
            await asyncio.to_thread(pyautogui.keyUp, modifier)

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        pyautogui = await _pyautogui()
        screen = await asyncio.to_thread(pyautogui.size)
        # A wheel event lands on whatever is under the pointer, so aim at the
        # region being scrolled (upstream moveMouseToScrollTarget).
        point = kwargs.get("point")
        target = (
            (int(point[0]), int(point[1]))
            if point
            else (screen.width // 2, screen.height // 2)
        )

        scroll_type = kwargs.get("scroll_type") or "singleAction"
        if scroll_type != "singleAction":
            edge = _EDGE_SCROLLS.get(scroll_type)
            if edge is None:
                raise ValueError(f"Unknown scroll type: {scroll_type}")
            await self._emit_detents(
                pyautogui,
                edge[0],
                edge[1],
                _EDGE_SCROLL_TOTAL_PX,
                target,
            )
            return

        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid scroll direction: {direction}")

        if not distance:
            axis = (
                screen.width if direction in ("left", "right") else screen.height
            )
            distance = max(1, round(axis * _DEFAULT_SCROLL_VIEWPORT_RATIO))

        horizontal = direction in ("left", "right")
        signs = {"down": -1, "up": 1, "right": 1, "left": -1}
        await self._emit_detents(
            pyautogui,
            "hscroll" if horizontal else "scroll",
            signs[direction],
            distance,
            target,
        )

    async def _emit_detents(
        self,
        pyautogui,
        wheel: str,
        sign: int,
        distance_px: int,
        target: Tuple[int, int],
    ) -> None:
        """Send one wheel notch per call: Chromium coalesces bulk deltas."""
        emit = getattr(pyautogui, wheel)
        for _ in range(_detent_count(distance_px)):
            await asyncio.to_thread(emit, sign, *target)
            await asyncio.sleep(_DETENT_DELAY)

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        """Swipe follows the finger-movement convention (upstream pointer):
        'up' drags the pointer towards the top of the screen."""
        pyautogui = await _pyautogui()
        screen = await asyncio.to_thread(pyautogui.size)
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid swipe direction: {direction}")
        distance = int(min(distance or screen.width // 4, screen.width, screen.height))
        half = distance // 2
        cx = min(max(screen.width // 2, half), max(half, screen.width - half))
        cy = min(
            max(screen.height // 2, half), max(half, screen.height - half)
        )
        offsets = {
            "up": (0, -distance),
            "down": (0, distance),
            "right": (distance, 0),
            "left": (-distance, 0),
        }
        dx, dy = offsets[direction]
        await self.drag_and_drop(
            (cx - dx // 2, cy - dy // 2), (cx + dx // 2, cy + dy // 2)
        )

    async def drag_and_drop(self, from_point, to_point) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.moveTo, int(from_point[0]), int(from_point[1]))
        await asyncio.to_thread(pyautogui.mouseDown)
        steps = 12
        for step in range(1, steps + 1):
            t = step / steps
            x = int(from_point[0] + (to_point[0] - from_point[0]) * t)
            y = int(from_point[1] + (to_point[1] - from_point[1]) * t)
            await asyncio.to_thread(pyautogui.moveTo, x, y)
            await asyncio.sleep(0.016)
        await asyncio.to_thread(pyautogui.mouseUp)

    async def long_press(self, x: float, y: float, duration: int = 1000) -> None:
        pyautogui = await _pyautogui()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))
        await asyncio.to_thread(pyautogui.mouseDown)
        await asyncio.sleep(duration / 1000)
        await asyncio.to_thread(pyautogui.mouseUp)


# pyautogui looks keys up in a per-platform table and silently ignores names it
# does not find, so every alias must resolve to a key valid on this OS or a
# combination degrades into a bare keystroke.
_KEY_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "del": "delete",
    "ins": "insert",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "page up": "pageup",
    "page down": "pagedown",
    "option": "alt",
    "control": "ctrl",
}

# Super/Command/Meta are the same modifier slot under different names per OS.
_SUPER_KEYS = {"command", "cmd", "meta", "super", "win", "windows", "winleft"}


def _normalize_key(key: str) -> str:
    text = key.strip()
    if not text:
        raise ValueError("keyboard_press requires a key name")
    lowered = text.lower()
    if lowered in _SUPER_KEYS:
        return "command" if _is_mac() else "winleft"
    if len(text) == 1:
        # pyautogui maps uppercase letters on every platform and presses shift
        # itself (isShiftCharacter); lowercasing here would type the wrong glyph.
        return text
    return _KEY_ALIASES.get(lowered, lowered)


def _is_mac() -> bool:
    import platform

    return platform.system() == "Darwin"
