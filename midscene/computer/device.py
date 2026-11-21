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
from typing import Dict, List, Optional

from loguru import logger

from midscene.computer.input_driver import (
    ComputerInputDriver,
    load_pyautogui as _pyautogui,
    normalize_key as _normalize_key_impl,
)
from midscene.computer.utils import is_mac as _is_mac
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
