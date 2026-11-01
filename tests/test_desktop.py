"""
Tests for the desktop automation device (upstream @midscene/computer).
All OS input goes through a fake pyautogui/pyperclip injected via
sys.modules, so the suite runs headless.
"""

import base64
import sys
from typing import List, Optional
from unittest.mock import MagicMock

import pytest


class FakePyAutoGUI:
    def __init__(self):
        self.calls: List[tuple] = []
        self.size_result = MagicMock(width=1920, height=1080)
        self.fail_on: Optional[str] = None
        # Same shape as pyautogui.KEY_NAMES: printable ASCII plus named keys.
        self.KEY_NAMES = [chr(code) for code in range(32, 127)] + [
            "enter",
            "escape",
            "backspace",
            "tab",
            "delete",
            "space",
            "up",
            "down",
            "left",
            "right",
            "pageup",
            "pagedown",
            "home",
            "end",
            "ctrl",
            "alt",
            "shift",
            "command",
            "win",
            "winleft",
            "option",
            "f1",
        ]

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "size":
                return self.size_result
            if name == "screenshot":
                from PIL import Image

                return Image.new(
                    "RGB",
                    (self.size_result.width, self.size_result.height),
                    (0, 0, 0),
                )
            if self.fail_on == name:
                raise RuntimeError(f"{name} failed")
            return None

        return record


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
def fake_pyautogui(monkeypatch):
    fake = FakePyAutoGUI()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.fixture
def fake_pyperclip(monkeypatch):
    fake = FakePyPerClip()
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    return fake


@pytest.fixture
def fast_wheel(monkeypatch):
    """Skip the per-notch pacing delay so unit tests stay quick."""
    from midscene.desktop import desktop as desktop_module

    monkeypatch.setattr(desktop_module, "_DETENT_DELAY", 0)


def _device(**options):
    from midscene.desktop.desktop import DesktopDevice

    return DesktopDevice(**options)


def _calls(fake, name):
    return [c for c in fake.calls if c[0] == name]


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
    # the root node describes the captured screen, not an empty box
    assert context.tree.node.rect.width == 1920
    assert context.tree.node.rect.height == 1080
    assert context.tree.node.center == (960, 540)


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
    monkeypatch.setattr("midscene.desktop.desktop._is_mac", lambda: False)
    device = _device()
    await device.input_text("你好桌面")
    # clipboard write happened with the text
    assert ("copy", "你好桌面") in fake_pyperclip.calls
    # paste hotkey sent (ctrl+v on non-mac)
    hotkeys = _calls(fake_pyautogui, "hotkey")
    assert hotkeys and list(hotkeys[0][1]) == ["ctrl", "v"]
    # old clipboard restored
    assert fake_pyperclip.value == "old-clipboard"


@pytest.mark.asyncio
async def test_input_text_uses_command_v_on_mac(
    fake_pyautogui, fake_pyperclip, monkeypatch
):
    monkeypatch.setattr("midscene.desktop.desktop._is_mac", lambda: True)
    device = _device()
    await device.input_text("text")
    assert list(_calls(fake_pyautogui, "hotkey")[0][1]) == ["command", "v"]


@pytest.mark.asyncio
async def test_input_text_restores_clipboard_on_failure(
    fake_pyautogui, fake_pyperclip
):
    fake_pyautogui.fail_on = "hotkey"
    device = _device()
    with pytest.raises(RuntimeError):
        await device.input_text("new text")
    # the text really reached the clipboard before the failure ...
    assert ("copy", "new text") in fake_pyperclip.calls
    # ... and the previous content was restored afterwards
    assert fake_pyperclip.calls[-1] == ("copy", "old-clipboard")


@pytest.mark.asyncio
async def test_keyboard_press_combination(fake_pyautogui):
    device = _device()
    await device.keyboard_press("Control+a")
    await device.keyboard_press("Enter")
    calls = [c for c in fake_pyautogui.calls if c[0] in ("hotkey", "press")]
    assert calls[0][0] == "hotkey" and list(calls[0][1]) == ["ctrl", "a"]
    assert calls[1][0] == "press" and calls[1][1] == ("enter",)


@pytest.mark.asyncio
async def test_super_keys_resolve_per_platform(fake_pyautogui, monkeypatch):
    """pyautogui silently drops unknown key names, so the modifier has to be
    named the way the current OS expects it."""
    monkeypatch.setattr("midscene.desktop.desktop._is_mac", lambda: True)
    await _device().keyboard_press("Meta+c")
    assert list(_calls(fake_pyautogui, "hotkey")[-1][1]) == ["command", "c"]

    monkeypatch.setattr("midscene.desktop.desktop._is_mac", lambda: False)
    await _device().keyboard_press("Command+c")
    assert list(_calls(fake_pyautogui, "hotkey")[-1][1]) == ["winleft", "c"]


@pytest.mark.asyncio
async def test_key_aliases_match_pyautogui_names(fake_pyautogui):
    from midscene.desktop.desktop import _normalize_key

    assert _normalize_key("page down") == "pagedown"
    assert _normalize_key("PageUp") == "pageup"
    assert _normalize_key("pgdn") == "pagedown"
    assert _normalize_key("Option") == "alt"
    assert _normalize_key("esc") == "escape"
    assert _normalize_key("ins") == "insert"
    assert _normalize_key("ArrowUp") == "up"
    assert _normalize_key("Return") == "enter"
    assert _normalize_key("Space") == "space"


@pytest.mark.asyncio
async def test_uppercase_keys_keep_their_shift(fake_pyautogui):
    """pyautogui maps uppercase single chars and presses shift itself, so case
    must survive normalization (a lowercase would type the wrong glyph)."""
    device = _device()
    await device.keyboard_press("A")
    assert ("press", ("A",), {}) in fake_pyautogui.calls
    await device.keyboard_press("Control+A")
    assert fake_pyautogui.calls[-1][1] == ("ctrl", "A")


@pytest.mark.asyncio
async def test_keyboard_press_rejects_empty_key(fake_pyautogui):
    with pytest.raises(ValueError):
        await _device().keyboard_press(" ")


@pytest.mark.asyncio
async def test_keyboard_press_rejects_unknown_key(fake_pyautogui):
    """pyautogui would ignore it, so the run would claim a press that never
    happened."""
    device = _device()
    with pytest.raises(ValueError, match="Unknown key name"):
        await device.keyboard_press("Hyper+F1")
    with pytest.raises(ValueError, match="Unknown key name"):
        await device.keyboard_press("page downn")
    assert not fake_pyautogui.calls


@pytest.mark.asyncio
async def test_keyboard_modifier_delay_paces_modifiers(fake_pyautogui):
    device = _device(keyboard_modifier_delay=1)
    await device.keyboard_press("Control+a")
    combo = [
        c for c in fake_pyautogui.calls if c[0] in ("keyDown", "press", "keyUp")
    ]
    assert [c[0] for c in combo] == ["keyDown", "press", "keyUp"]
    assert combo[0][1] == ("ctrl",)
    assert combo[1][1] == ("a",)
    assert not _calls(fake_pyautogui, "hotkey")


@pytest.mark.asyncio
async def test_scroll_sends_wheel_notches_for_pixels(
    fake_pyautogui, fast_wheel
):
    device = _device()
    await device.scroll("down", 500)
    scrolls = _calls(fake_pyautogui, "scroll")
    # 500px at ~100px per notch, one notch per event like upstream
    assert len(scrolls) == 5
    assert {c[1] for c in scrolls} == {(-1, 960, 540)}


@pytest.mark.asyncio
async def test_scroll_default_distance_is_viewport_relative(
    fake_pyautogui, fast_wheel
):
    await _device().scroll("down")
    # 0.7 * 1080 = 756px -> 8 notches
    assert len(_calls(fake_pyautogui, "scroll")) == 8


@pytest.mark.asyncio
async def test_scroll_accepts_float_distances(fake_pyautogui, fast_wheel):
    await _device().scroll("down", 480.5)
    assert len(_calls(fake_pyautogui, "scroll")) == 5


@pytest.mark.asyncio
async def test_scroll_edge_types_pick_the_right_axis(fake_pyautogui, fast_wheel):
    device = _device()
    await device.scroll("down", scroll_type="scrollToBottom")
    assert [c[1][0] for c in _calls(fake_pyautogui, "scroll")] == [-1] * 200
    fake_pyautogui.calls.clear()

    await device.scroll("down", scroll_type="scrollToLeft")
    assert [c[1][0] for c in _calls(fake_pyautogui, "hscroll")] == [-1] * 200
    fake_pyautogui.calls.clear()

    await device.scroll("down", scroll_type="scrollToTop")
    assert [c[1][0] for c in _calls(fake_pyautogui, "scroll")] == [1] * 200


@pytest.mark.asyncio
async def test_scroll_aims_at_the_located_region(
    fake_pyautogui, fast_wheel
):
    await _device().scroll("down", 100, point=(300, 700))
    assert _calls(fake_pyautogui, "scroll")[0][1] == (-1, 300, 700)


@pytest.mark.asyncio
async def test_scroll_rejects_unknown_scroll_type(fake_pyautogui, fast_wheel):
    with pytest.raises(ValueError):
        await _device().scroll("down", scroll_type="scrollSideways")


@pytest.mark.asyncio
async def test_drag_and_drop_interpolates(fake_pyautogui):
    device = _device()
    await device.drag_and_drop((0, 0), (100, 100))
    moves = _calls(fake_pyautogui, "moveTo")
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
async def test_swipe_moves_the_pointer_in_the_requested_direction(
    fake_pyautogui,
):
    device = _device()
    await device.swipe("up", distance=200)
    moves = _calls(fake_pyautogui, "moveTo")
    # finger convention: 'up' ends above where it started (android parity)
    assert moves[-1][1][1] < moves[0][1][1]
    assert moves[-1][1][0] == moves[0][1][0]
    assert ("mouseDown", (), {}) in fake_pyautogui.calls

    fake_pyautogui.calls.clear()
    await device.swipe("left", distance=400)
    moves = _calls(fake_pyautogui, "moveTo")
    assert moves[-1][1][0] < moves[0][1][0]


@pytest.mark.asyncio
async def test_swipe_stays_on_screen(fake_pyautogui):
    from midscene.desktop.desktop import DesktopDevice

    async def record_drag(from_point, to_point):
        assert 0 <= from_point[0] <= 1920 and 0 <= from_point[1] <= 1080
        assert 0 <= to_point[0] <= 1920 and 0 <= to_point[1] <= 1080

    device = DesktopDevice()
    device.drag_and_drop = record_drag
    await device.swipe("right", distance=4000)


@pytest.mark.asyncio
async def test_clear_input_selects_all_then_deletes(
    fake_pyautogui, monkeypatch
):
    monkeypatch.setattr("midscene.desktop.desktop._is_mac", lambda: False)
    await _device().clear_input()
    combo = list(_calls(fake_pyautogui, "hotkey")[0][1])
    assert combo == ["ctrl", "a"]
    assert ("press", ("backspace",), {}) in fake_pyautogui.calls


def test_computer_action_space_excludes_pinch():
    from midscene.core.actions import build_action_space_for

    names = [a.name for a in build_action_space_for("computer")]
    assert "Pinch" not in names
    assert {"Tap", "Input", "KeyboardPress", "Scroll", "DragAndDrop"} <= set(names)


def test_computer_action_space_has_pointer_swipe_without_long_press():
    """Upstream exposes Swipe on the computer device but keeps LongPress out of
    the plannable space (see the TODO in build_action_space_for)."""
    from midscene.core.actions import build_action_space_for

    names = [a.name for a in build_action_space_for("computer")]
    assert "Swipe" in names
    assert "LongPress" not in names


def test_display_id_is_rejected():
    """pyautogui grabs the primary display only; declaring one must not pass
    silently."""
    with pytest.raises(NotImplementedError):
        _device(display_id="1")


@pytest.mark.asyncio
async def test_missing_desktop_extra_reports_friendly_error(monkeypatch):
    from midscene.desktop import desktop as desktop_module

    monkeypatch.setitem(sys.modules, "pyautogui", None)
    with pytest.raises(ImportError, match=r"midscene-python\[desktop\]"):
        await desktop_module._pyautogui()


def test_clear_input_is_plannable_on_desktop(fake_pyautogui):
    from midscene.desktop import DesktopAgent

    names = [a.name for a in DesktopAgent().action_space]
    assert "ClearInput" in names


def test_desktop_agent_uses_computer_interface(fake_pyautogui):
    from midscene.desktop import DesktopAgent

    agent = DesktopAgent()
    assert agent.interface_type.value == "computer"
