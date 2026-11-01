"""
Tests for the desktop automation device (upstream @midscene/computer).
All OS input goes through a fake pyautogui/pyperclip injected via
sys.modules, so the suite runs headless.
"""

import base64
import sys
from typing import List
from unittest.mock import MagicMock

import pytest


class FakePyAutoGUI:
    def __init__(self):
        self.calls: List[tuple] = []
        self.size_result = MagicMock(width=1920, height=1080)
        self.screenshot_result = MagicMock()

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "size":
                return self.size_result
            if name == "screenshot":
                from PIL import Image

                return Image.new("RGB", (1920, 1080), (0, 0, 0))
            return None

        return record


@pytest.fixture
def fake_pyautogui(monkeypatch):
    fake = FakePyAutoGUI()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


class FakePyPerClip:
    def __init__(self):
        self.value = "old-clipboard"
        self.calls: List[tuple] = []

    def paste(self):
        return self.value

    def copy(self, text):
        self.calls.append(("copy", text))
        self.value = text


@pytest.fixture
def fake_pyperclip(monkeypatch):
    fake = FakePyPerClip()
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    return fake


def _device():
    from midscene.desktop.desktop import DesktopDevice

    return DesktopDevice()


@pytest.mark.asyncio
async def test_get_context_captures_screen(fake_pyautogui):
    from midscene.core.types import InterfaceType

    device = _device()
    assert device.interface_type == InterfaceType.COMPUTER
    context = await device.get_context()
    assert context.size.width == 1920
    assert context.size.height == 1080
    assert context.screenshot_base64  # png payload present
    base64.b64decode(context.screenshot_base64)


@pytest.mark.asyncio
async def test_tap_and_click_variants(fake_pyautogui):
    device = _device()
    await device.tap(100, 200)
    await device.right_click(10, 20)
    await device.double_click(30, 40)
    await device.middle_click(50, 60)
    names = [c[0] for c in fake_pyautogui.calls]
    assert names.count("click") == 4
    assert fake_pyautogui.calls[0][1] == (100, 200)
    assert fake_pyautogui.calls[1][2] == {"button": "right"}
    assert fake_pyautogui.calls[2][2] == {"clicks": 2}


@pytest.mark.asyncio
async def test_input_text_uses_clipboard_paste(fake_pyautogui, fake_pyperclip, monkeypatch):

    monkeypatch.setattr(
        "midscene.desktop.desktop._is_mac", lambda: False
    )
    device = _device()
    await device.input_text("你好桌面")
    # clipboard write happened with the text
    assert ("copy", "你好桌面") in fake_pyperclip.calls
    # paste hotkey sent (ctrl+v on non-mac)
    hotkeys = [c for c in fake_pyautogui.calls if c[0] == "hotkey"]
    assert hotkeys and list(hotkeys[0][1]) == ["ctrl", "v"]
    # old clipboard restored
    assert fake_pyperclip.value == "old-clipboard"


@pytest.mark.asyncio
async def test_input_text_restores_clipboard_on_failure(
    fake_pyautogui, fake_pyperclip
):
    device = _device()

    async def failing_hotkey(*keys):
        raise RuntimeError("hotkey failed")

    import asyncio

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "midscene.desktop.desktop.asyncio.to_thread",
            lambda fn, *a, **k: failing_hotkey(*a) if fn.__name__ == "hotkey" else asyncio.to_thread(fn, *a, **k),
        )
        with pytest.raises(RuntimeError):
            await device.input_text("text")
    assert fake_pyperclip.value == "old-clipboard"


@pytest.mark.asyncio
async def test_keyboard_press_combination(fake_pyautogui):
    device = _device()
    await device.keyboard_press("Control+A")
    await device.keyboard_press("Enter")
    calls = [c for c in fake_pyautogui.calls if c[0] in ("hotkey", "press")]
    assert calls[0][0] == "hotkey" and list(calls[0][1]) == ["ctrl", "a"]
    assert calls[1][0] == "press" and calls[1][1] == ("enter",)


@pytest.mark.asyncio
async def test_scroll_directions(fake_pyautogui):
    device = _device()
    await device.scroll("down", 500)
    await device.scroll("up", 500)
    await device.scroll("right", 300)
    scrolls = [c for c in fake_pyautogui.calls if c[0] in ("scroll", "hscroll")]
    assert scrolls[0][1] == (-500,)
    assert scrolls[1][1] == (500,)
    assert scrolls[2][0] == "hscroll"


@pytest.mark.asyncio
async def test_drag_and_drop_interpolates(fake_pyautogui):
    device = _device()
    await device.drag_and_drop((0, 0), (100, 100))
    moves = [c for c in fake_pyautogui.calls if c[0] == "moveTo"]
    assert moves[0][1] == (0, 0)
    assert moves[-1][1] == (100, 100)
    assert ("mouseDown", (), {}) in fake_pyautogui.calls
    assert ("mouseUp", (), {}) in fake_pyautogui.calls


@pytest.mark.asyncio
async def test_long_press_holds_button(fake_pyautogui):
    device = _device()
    await device.long_press(10, 10, duration=10)
    order = [c[0] for c in fake_pyautogui.calls]
    assert order.index("mouseDown") < order.index("mouseUp")


@pytest.mark.asyncio
async def test_swipe_uses_drag(fake_pyautogui):
    device = _device()
    await device.swipe("up", distance=200)
    moves = [c for c in fake_pyautogui.calls if c[0] == "moveTo"]
    assert len(moves) >= 2
    assert ("mouseDown", (), {}) in fake_pyautogui.calls


def test_computer_action_space_excludes_pinch():
    from midscene.core.actions import build_action_space_for

    names = [a.name for a in build_action_space_for("computer")]
    assert "Pinch" not in names
    assert {"Tap", "Input", "KeyboardPress", "Scroll", "DragAndDrop"} <= set(names)


def test_desktop_agent_uses_computer_interface(fake_pyautogui):
    from midscene.desktop import DesktopAgent

    agent = DesktopAgent()
    assert agent.interface_type.value == "computer"
