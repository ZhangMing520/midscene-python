"""Desktop input driver (upstream computer/src/input-driver.ts).

Upstream wraps libnut; the Python backend uses pyautogui. Keeping pointer and
keyboard handling here lets ``device.py`` stay focused on capture/context.
"""

import asyncio
import math
import subprocess
from typing import Callable, Dict, List, Optional, Set, Tuple

from loguru import logger

from midscene.core.types import Size

_PIXELS_PER_DETENT = 100
_MAX_DETENTS = 200
_DETENT_DELAY = 0.03
_EDGE_SCROLL_TOTAL_PX = 50_000
_DEFAULT_SCROLL_VIEWPORT_RATIO = 0.7
_MOUSE_COORDINATE_TOLERANCE_PX = 5

# macOS System Events key codes (upstream apple-script-keyboard.ts).
_APPLE_SCRIPT_KEY_CODES = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "delete": 51,
    "escape": 53,
    "forwarddelete": 117,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

_APPLE_SCRIPT_MODIFIER_KEYS = {
    "command": "command",
    "cmd": "command",
    "control": "control",
    "ctrl": "control",
    "shift": "shift",
    "alt": "option",
    "option": "option",
    "meta": "command",
}


def _build_apple_script_key_press(
    key: str, modifiers: Optional[List[str]] = None
) -> str:
    """Build the System Events script for one key press."""
    key_code = _APPLE_SCRIPT_KEY_CODES.get(key.lower())
    if key_code is not None:
        command = f"key code {key_code}"
    else:
        escaped = key.replace("\\", "\\\\").replace('"', '\\"')
        command = f'keystroke "{escaped}"'

    modifier_keys = [
        _APPLE_SCRIPT_MODIFIER_KEYS[modifier.lower()]
        for modifier in (modifiers or [])
        if modifier.lower() in _APPLE_SCRIPT_MODIFIER_KEYS
    ]
    modifier_clause = ""
    if modifier_keys:
        clause = ", ".join(f"{modifier} down" for modifier in modifier_keys)
        modifier_clause = f" using {{{clause}}}"
    return (
        f'tell application "System Events" to {command}{modifier_clause}'
    )


def _run_apple_script(script: str) -> None:
    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )


def _point_xy(point) -> Tuple[int, int]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return int(point.x), int(point.y)
    return int(point[0]), int(point[1])


# (pyautogui function, sign) per upstream EDGE_SCROLL_SPEC.
_EDGE_SCROLLS = {
    "scrollToTop": ("scroll", 1),
    "scrollToBottom": ("scroll", -1),
    "scrollToLeft": ("hscroll", -1),
    "scrollToRight": ("hscroll", 1),
}


def import_pyautogui():
    try:
        import pyautogui
    except ImportError as e:
        raise ImportError(
            "Computer automation needs pyautogui; install the computer extra "
            "with: pip install midscene-python[computer]"
        ) from e
    # Drags and swipes end near screen edges, which is exactly where pyautogui
    # raises its FailSafeException.
    pyautogui.FAILSAFE = False
    return pyautogui


async def load_pyautogui():
    """Import off the event loop: the first import loads the OS backends."""
    return await asyncio.to_thread(import_pyautogui)


def load_pyperclip():
    try:
        import pyperclip

        return pyperclip
    except ImportError:  # pragma: no cover - optional helper
        return None


def detent_count(distance_px: float) -> int:
    """Pixel distance -> wheel notches, at least one and never more than 200."""
    notches = -(-abs(int(distance_px)) // _PIXELS_PER_DETENT)
    return min(_MAX_DETENTS, max(1, notches))


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


def normalize_key(key: str, is_mac: Callable[[], bool]) -> str:
    text = key.strip()
    if not text:
        raise ValueError("keyboard_press requires a key name")
    lowered = text.lower()
    if lowered in _SUPER_KEYS:
        return "command" if is_mac() else "winleft"
    if len(text) == 1:
        # pyautogui maps uppercase letters on every platform and presses shift
        # itself (isShiftCharacter); lowercasing here would type the wrong glyph.
        return text
    return _KEY_ALIASES.get(lowered, lowered)


class ComputerInputDriver:
    """Pointer/keyboard actions backed by pyautogui."""

    def __init__(
        self,
        is_mac: Callable[[], bool],
        keyboard_modifier_delay: int = 0,
    ):
        self._is_mac = is_mac
        self.keyboard_modifier_delay = keyboard_modifier_delay
        self._destroyed = False
        self._pending_input_delays: Set[asyncio.Future] = set()

    async def _pg(self):
        return await load_pyautogui()

    # --- libnut-shaped primitives (upstream input-driver.ts) -----------------

    def destroy(self) -> None:
        """Mark the driver unusable and reject in-flight input delays."""
        if self._destroyed:
            return
        self._destroyed = True
        self._reject_pending_input_delays()

    async def get_screen_size(self) -> Size:
        self._assert_active("getScreenSize")
        pyautogui = await self._pg()
        screen = await asyncio.to_thread(pyautogui.size)
        return Size(width=int(screen.width), height=int(screen.height))

    async def get_mouse_pos(self) -> Dict[str, int]:
        self._assert_active("getMousePos")
        pyautogui = await self._pg()
        position = await asyncio.to_thread(pyautogui.position)
        x, y = _point_xy(position)
        return {"x": x, "y": y}

    async def move_mouse(self, x: float, y: float) -> None:
        self._assert_active("moveMouse")
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))

    async def assert_mouse_position(
        self, target_x: float, target_y: float, context: str
    ) -> Dict[str, float]:
        """Fail when the pointer drifted more than the tolerated distance."""
        self._assert_active("assertMousePosition")
        current = await self.get_mouse_pos()
        drift = {
            "x": current["x"] - target_x,
            "y": current["y"] - target_y,
        }
        if (
            abs(drift["x"]) > _MOUSE_COORDINATE_TOLERANCE_PX
            or abs(drift["y"]) > _MOUSE_COORDINATE_TOLERANCE_PX
        ):
            raise RuntimeError(
                f"{context}: expected ({target_x}, {target_y}), "
                f"got ({current['x']}, {current['y']}), "
                f"drift=({drift['x']}, {drift['y']})"
            )
        return drift

    async def focus_active_window(self) -> bool:
        """Upstream uses libnut window APIs; pyautogui has no equivalent."""
        self._assert_active("focusActiveWindow")
        return False

    async def mouse_click(
        self, button: Optional[str] = None, double: bool = False
    ) -> None:
        self._assert_active("mouseClick")
        pyautogui = await self._pg()
        kwargs: Dict[str, object] = {"clicks": 2 if double else 1}
        if button is not None:
            kwargs["button"] = button
        await asyncio.to_thread(pyautogui.click, **kwargs)

    async def mouse_toggle(self, state: str, button: str = "left") -> None:
        self._assert_active("mouseToggle")
        if state not in ("up", "down"):
            raise ValueError('mouseToggle state must be "up" or "down"')
        pyautogui = await self._pg()
        toggle = pyautogui.mouseDown if state == "down" else pyautogui.mouseUp
        await asyncio.to_thread(toggle, button=button)

    async def scroll_mouse(self, x: float, y: float) -> None:
        """Scroll at the current pointer position (libnut.scrollMouse)."""
        self._assert_active("scrollMouse")
        pyautogui = await self._pg()
        if x:
            await asyncio.to_thread(pyautogui.hscroll, int(x))
        if y:
            await asyncio.to_thread(pyautogui.scroll, int(y))

    async def emit_scroll_detents(
        self, dx: float, dy: float, detents: int, delay_ms: float
    ) -> None:
        """Emit one wheel event per detent, pacing calls with ``delay_ms``."""
        self._assert_active("emitScrollDetents")
        count = int(detents)
        for index in range(count):
            await self.scroll_mouse(dx, dy)
            if index < count - 1:
                await self.delay(delay_ms)

    async def key_tap(
        self, key: str, modifiers: Optional[List[str]] = None
    ) -> None:
        self._assert_active("keyTap")
        pyautogui = await self._pg()
        keys = [
            normalize_key(modifier, self._is_mac)
            for modifier in (modifiers or [])
        ]
        keys.append(normalize_key(key, self._is_mac))
        self._validate_keys(pyautogui, keys)
        # libnut's keyTap is always a compact tap; pacing belongs to
        # keyTapWithModifierDelay.
        await self._press_combo(pyautogui, keys, delay_ms=0)

    async def key_toggle(
        self,
        key: str,
        state: str,
        modifiers: Optional[List[str]] = None,
    ) -> None:
        self._assert_active("keyToggle")
        if state not in ("up", "down"):
            raise ValueError('keyToggle state must be "up" or "down"')
        pyautogui = await self._pg()
        key_name = normalize_key(key, self._is_mac)
        modifier_names = [
            normalize_key(modifier, self._is_mac)
            for modifier in (modifiers or [])
        ]
        self._validate_keys(pyautogui, modifier_names + [key_name])
        for modifier in modifier_names:
            await asyncio.to_thread(pyautogui.keyDown, modifier)
        try:
            toggle = (
                pyautogui.keyDown if state == "down" else pyautogui.keyUp
            )
            await asyncio.to_thread(toggle, key_name)
        finally:
            for modifier in reversed(modifier_names):
                try:
                    await asyncio.to_thread(pyautogui.keyUp, modifier)
                except Exception as error:
                    logger.debug(
                        f'Failed to release modifier key "{modifier}": {error}'
                    )

    async def key_tap_with_modifier_delay(
        self, key: str, modifiers: List[str], delay_ms: float
    ) -> None:
        """Expand a modified key tap into observable modifier transitions."""
        self._assert_active("keyTapWithModifierDelay")
        unique_modifiers = list(dict.fromkeys(modifiers or []))
        if not unique_modifiers:
            await self.key_tap(key)
            return
        if delay_ms == 0:
            await self.key_tap(key, unique_modifiers)
            return

        pyautogui = await self._pg()
        key_name = normalize_key(key, self._is_mac)
        modifier_names = [
            normalize_key(modifier, self._is_mac)
            for modifier in unique_modifiers
        ]
        pressed: List[str] = []
        failure: Optional[Exception] = None
        try:
            for modifier in modifier_names:
                await asyncio.to_thread(pyautogui.keyDown, modifier)
                pressed.append(modifier)
                await self.delay(delay_ms)
            await asyncio.to_thread(pyautogui.press, key_name)
            await self.delay(delay_ms)
        except Exception as error:
            failure = error

        for modifier in reversed(pressed):
            try:
                await asyncio.to_thread(pyautogui.keyUp, modifier)
            except Exception as error:
                if failure is None:
                    failure = RuntimeError(
                        f'Failed to release modifier key "{modifier}"'
                    )
                logger.debug(
                    f'Failed to release modifier key "{modifier}": {error}'
                )
            if failure is None:
                try:
                    await self.delay(delay_ms)
                except Exception as error:
                    failure = error

        if failure is not None:
            raise failure

    async def type_string(self, text: str) -> None:
        self._assert_active("typeString")
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.write, text)

    async def send_key_via_apple_script(
        self, key: str, modifiers: Optional[List[str]] = None
    ) -> None:
        self._assert_active("sendKeyViaAppleScript")
        modifiers = list(modifiers or [])
        if not self._is_mac():
            # Upstream only reaches this on macOS; pyautogui is the
            # cross-platform fallback for the Python backend.
            await self.key_tap(key, modifiers)
            return
        script = _build_apple_script_key_press(key, modifiers)
        logger.debug(f"sendKeyViaAppleScript: {script}")
        await asyncio.to_thread(_run_apple_script, script)

    async def send_key(
        self, key: str, modifiers: Optional[List[str]] = None
    ) -> None:
        modifiers = list(modifiers or [])
        if self._is_mac():
            await self.send_key_via_apple_script(key, modifiers)
            return
        if modifiers:
            await self.key_tap(key, modifiers)
        else:
            await self.key_tap(key)

    async def run_phased_scroll(
        self, direction: str, pixels: float, steps: int
    ) -> bool:
        self._assert_active("runPhasedScroll")
        from midscene.computer.device import run_phased_scroll

        return await asyncio.to_thread(
            run_phased_scroll, direction, pixels, steps
        )

    async def delay(self, ms: float) -> None:
        """Sleep, rejecting the wait when the driver is destroyed."""
        self._assert_active("delay")
        loop = asyncio.get_running_loop()
        wait: asyncio.Future = loop.create_future()
        self._pending_input_delays.add(wait)

        def resolve() -> None:
            if wait.done():
                return
            self._pending_input_delays.discard(wait)
            try:
                self._assert_active("delay")
                wait.set_result(None)
            except Exception as error:
                wait.set_exception(error)

        timer = loop.call_later(max(0.0, ms) / 1000, resolve)
        try:
            await wait
        finally:
            timer.cancel()
            self._pending_input_delays.discard(wait)

    async def smooth_move_mouse(
        self, target_x: float, target_y: float, steps: int, step_delay: float
    ) -> None:
        self._assert_active("smoothMoveMouse")
        current = await self.get_mouse_pos()
        for index in range(1, int(steps) + 1):
            step_x = int(
                math.floor(
                    current["x"]
                    + (target_x - current["x"]) * index / steps
                    + 0.5
                )
            )
            step_y = int(
                math.floor(
                    current["y"]
                    + (target_y - current["y"]) * index / steps
                    + 0.5
                )
            )
            await self.move_mouse(step_x, step_y)
            await self.delay(step_delay)

    async def with_mouse_button(self, button: str, run) -> object:
        """Hold ``button`` down while awaiting ``run``, then release it."""
        self._assert_active("withMouseButton")
        await self.mouse_toggle("down", button)
        try:
            return await run()
        finally:
            await self._release_mouse_button(button)

    def _assert_active(self, method_name: str) -> None:
        if self._destroyed:
            raise self._create_destroyed_error(method_name)

    @staticmethod
    def _create_destroyed_error(method_name: str) -> RuntimeError:
        return RuntimeError(
            f"ComputerDevice has been destroyed (cannot run {method_name})"
        )

    @staticmethod
    def _validate_keys(pyautogui, keys: List[str]) -> None:
        for name in keys:
            if name not in pyautogui.KEY_NAMES:
                raise ValueError(f"Unknown key name: {name!r}")

    async def _release_mouse_button(self, button: str) -> None:
        try:
            pyautogui = await self._pg()
            await asyncio.to_thread(pyautogui.mouseUp, button=button)
        except Exception as error:
            logger.debug(f"Failed to release mouse button {button}: {error}")

    def _reject_pending_input_delays(self) -> None:
        error = self._create_destroyed_error("in-flight input")
        for wait in list(self._pending_input_delays):
            if not wait.done():
                wait.set_exception(error)
        self._pending_input_delays.clear()

    async def tap(self, x: float, y: float) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.click, int(x), int(y))

    async def right_click(self, x: float, y: float) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="right")

    async def middle_click(self, x: float, y: float) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="middle")

    async def double_click(self, x: float, y: float) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), clicks=2)

    async def hover(self, x: float, y: float) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))

    async def input_text(self, text: str) -> None:
        """Paste text through the clipboard (upstream typeViaClipboard):
        save old clipboard, write text, simulate Ctrl+V / Cmd+V, restore."""
        if not text:
            return
        pyautogui = await self._pg()
        pyperclip = load_pyperclip()
        paste_shortcut = ["command", "v"] if self._is_mac() else ["ctrl", "v"]

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
        await self.keyboard_press(
            "Command+a" if self._is_mac() else "Control+a"
        )
        await asyncio.sleep(0.05)
        await self.keyboard_press("Backspace")

    async def keyboard_press(self, key: str) -> None:
        pyautogui = await self._pg()
        keys = [
            normalize_key(part, self._is_mac)
            for part in key.split("+")
            if part.strip()
        ]
        if not keys:
            raise ValueError(f"Invalid key name: {key!r}")
        for name in keys:
            # An unknown name is a silent no-op in every pyautogui backend, so
            # fail instead of reporting a shortcut that never happened.
            if name not in pyautogui.KEY_NAMES:
                raise ValueError(f"Unknown key name: {name!r}")
        await self._press_combo(pyautogui, keys)

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret with arrow keys (upstream computer cursorMove)."""
        if direction not in ("left", "right"):
            raise ValueError('CursorMove direction must be "left" or "right"')
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.keyboard_press(arrow_key)

    async def _press_combo(
        self,
        pyautogui,
        keys: List[str],
        delay_ms: Optional[int] = None,
    ) -> None:
        """Tap the last key with the leading keys held as modifiers.

        `keyboard_modifier_delay` paces the modifier down/up like upstream
        `keyTapWithModifierDelay`; the default 0 uses pyautogui's hotkey.
        """
        if len(keys) == 1:
            await asyncio.to_thread(pyautogui.press, keys[0])
            return

        effective_delay = (
            self.keyboard_modifier_delay if delay_ms is None else delay_ms
        )
        delay = effective_delay / 1000
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
        pyautogui = await self._pg()
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
        for _ in range(detent_count(distance_px)):
            await asyncio.to_thread(emit, sign, *target)
            await asyncio.sleep(_DETENT_DELAY)

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        """Swipe follows the finger-movement convention (upstream pointer):
        'up' drags the pointer towards the top of the screen."""
        pyautogui = await self._pg()
        screen = await asyncio.to_thread(pyautogui.size)
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid swipe direction: {direction}")
        distance = int(
            min(distance or screen.width // 4, screen.width, screen.height)
        )
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

    async def swipe_points(
        self,
        start: List[float],
        end: List[float],
        duration: Optional[int] = None,
    ) -> None:
        """Endpoint pointer swipe between two logical points (upstream swipe)."""
        await self.drag_and_drop((start[0], start[1]), (end[0], end[1]))

    async def drag_and_drop(self, from_point, to_point) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(
            pyautogui.moveTo, int(from_point[0]), int(from_point[1])
        )
        await asyncio.to_thread(pyautogui.mouseDown)
        steps = 12
        for step in range(1, steps + 1):
            t = step / steps
            x = int(from_point[0] + (to_point[0] - from_point[0]) * t)
            y = int(from_point[1] + (to_point[1] - from_point[1]) * t)
            await asyncio.to_thread(pyautogui.moveTo, x, y)
            await asyncio.sleep(0.016)
        await asyncio.to_thread(pyautogui.mouseUp)

    async def long_press(
        self, x: float, y: float, duration: int = 1000
    ) -> None:
        pyautogui = await self._pg()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))
        await asyncio.to_thread(pyautogui.mouseDown)
        await asyncio.sleep(duration / 1000)
        await asyncio.to_thread(pyautogui.mouseUp)


__all__ = [
    "ComputerInputDriver",
    "detent_count",
    "import_pyautogui",
    "load_pyautogui",
    "load_pyperclip",
    "normalize_key",
]
