"""Desktop automation device (Windows / macOS / Linux).

Synced from upstream packages/computer/src (v1.17.4). The device captures
the full screen and drives the OS pointer/keyboard through pyautogui; text
input is pasted through the clipboard by default (upstream typeViaClipboard)
so CJK text and IME interference are handled the same way as upstream.
"""

import asyncio
import base64
import io
import os
from typing import List, Optional

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


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    return pyautogui


def _pyperclip():
    try:
        import pyperclip

        return pyperclip
    except ImportError:  # pragma: no cover - optional helper
        return None


class DesktopDevice(AbstractInterface):
    """Local desktop device: full-screen capture + OS-level input."""

    def __init__(
        self,
        display_id: Optional[int] = None,
        keyboard_modifier_delay: int = 50,
    ):
        self.display_id = display_id
        self.keyboard_modifier_delay = keyboard_modifier_delay

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.COMPUTER

    async def get_context(self) -> UIContext:
        try:
            pyautogui = await asyncio.to_thread(_pyautogui)
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
                        rect=Rect(left=0, top=0, width=0, height=0),
                        center=(0, 0),
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
            "input", "key_press", "scroll", "drag", "long_press", "swipe",
        ]

    async def tap(self, x: float, y: float) -> None:
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y))

    async def right_click(self, x: float, y: float) -> None:
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="right")

    async def middle_click(self, x: float, y: float) -> None:
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), button="middle")

    async def double_click(self, x: float, y: float) -> None:
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.click, int(x), int(y), clicks=2)

    async def hover(self, x: float, y: float) -> None:
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))

    async def input_text(self, text: str) -> None:
        """Paste text through the clipboard (upstream typeViaClipboard):
        save old clipboard, write text, simulate Ctrl+V / Cmd+V, restore."""
        if not text:
            return
        pyautogui = _pyautogui()
        pyperclip = _pyperclip()
        paste_shortcut = ["command", "v"] if os.name == "posix" and _is_mac() else ["ctrl", "v"]

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
                await asyncio.to_thread(pyautogui.hotkey, *paste_shortcut)
                await asyncio.sleep(0.1)
            else:
                await asyncio.to_thread(pyautogui.write, text)
        finally:
            if pyperclip is not None and old_clipboard:
                try:
                    await asyncio.to_thread(pyperclip.copy, old_clipboard)
                except Exception:
                    logger.debug("failed to restore clipboard content")

    async def keyboard_press(self, key: str) -> None:
        pyautogui = _pyautogui()
        parts = [p for p in key.split("+") if p]
        if len(parts) > 1:
            keys = [_normalize_key(p) for p in parts]
            await asyncio.to_thread(pyautogui.hotkey, *keys)
        else:
            await asyncio.to_thread(pyautogui.press, _normalize_key(key))

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        if kwargs.get("scroll_type", "singleAction").startswith("scrollTo"):
            target = kwargs["scroll_type"].replace("scrollTo", "").lower()
            pyautogui = _pyautogui()
            screen = await asyncio.to_thread(pyautogui.size)
            center = (screen.width // 2, screen.height // 2)
            if target == "bottom":
                await asyncio.to_thread(pyautogui.scroll, -100000, *center)
            elif target in ("top", "left"):
                await asyncio.to_thread(pyautogui.scroll, 100000, *center)
            elif target == "right":
                await asyncio.to_thread(pyautogui.hscroll, 100000, *center)
            return

        distance = distance or 500
        pyautogui = _pyautogui()
        if direction == "down":
            await asyncio.to_thread(pyautogui.scroll, -distance)
        elif direction == "up":
            await asyncio.to_thread(pyautogui.scroll, distance)
        elif direction == "right":
            await asyncio.to_thread(pyautogui.hscroll, distance)
        elif direction == "left":
            await asyncio.to_thread(pyautogui.hscroll, -distance)
        else:
            raise ValueError(f"Invalid scroll direction: {direction}")

    async def swipe(
        self, direction: str, distance: Optional[int] = None
    ) -> None:
        """Swipe follows the finger-movement convention (upstream pointer)."""
        pyautogui = _pyautogui()
        screen = await asyncio.to_thread(pyautogui.size)
        distance = distance or screen.width // 4
        cx, cy = screen.width // 2, screen.height // 2
        offsets = {
            "up": (0, distance),
            "down": (0, -distance),
            "right": (-distance, 0),
            "left": (distance, 0),
        }
        if direction not in offsets:
            raise ValueError(f"Invalid swipe direction: {direction}")
        dx, dy = offsets[direction]
        await self.drag_and_drop((cx - dx // 2, cy - dy // 2), (cx + dx // 2, cy + dy // 2))

    async def drag_and_drop(self, from_point, to_point) -> None:
        pyautogui = _pyautogui()
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
        pyautogui = _pyautogui()
        await asyncio.to_thread(pyautogui.moveTo, int(x), int(y))
        await asyncio.to_thread(pyautogui.mouseDown)
        await asyncio.sleep(duration / 1000)
        await asyncio.to_thread(pyautogui.mouseUp)


_KEY_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "esc": "escape",
    "escape": "escape",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "control": "ctrl",
    "meta": "winleft",
    "cmd": "winleft",
}


def _normalize_key(key: str) -> str:
    normalized = key.strip().lower()
    if len(normalized) == 1:
        return normalized  # pyautogui hotkey keys are case-insensitive
    return _KEY_ALIASES.get(normalized, normalized)


def _is_mac() -> bool:
    import platform

    return platform.system() == "Darwin"
