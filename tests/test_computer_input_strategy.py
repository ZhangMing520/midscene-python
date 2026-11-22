"""Port of upstream packages/computer/tests/unit-test/input-strategy.test.ts.

Upstream drives libnut's ``keyTap``/``keyTapWithModifierDelay``/``typeString``.
The Python driver is pyautogui-backed, so the same contracts are asserted on
pyautogui calls: explicit modifier phases when a modifier delay is configured,
pyautogui's ``hotkey`` shortcut when it is zero, and the select-all/delete
shortcut used before replacing input.
"""

import sys
from typing import List
from unittest.mock import MagicMock

import pytest


class FakePyAutoGUI:
    def __init__(self):
        self.calls: List[tuple] = []
        self.size_result = MagicMock(width=1920, height=1080)
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
        ]

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "size":
                return self.size_result
            return None

        return record


@pytest.fixture
def fake_pyautogui(monkeypatch):
    fake = FakePyAutoGUI()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.fixture(autouse=True)
def _not_mac(monkeypatch):
    monkeypatch.setattr("midscene.computer.device._is_mac", lambda: False)


def _device(**options):
    from midscene.computer.device import ComputerDevice

    return ComputerDevice(**options)


def _calls(fake, name):
    return [c for c in fake.calls if c[0] == name]


@pytest.mark.asyncio
async def test_uses_explicit_modifier_phases_when_modifier_delay_is_configured(
    fake_pyautogui,
):
    """uses explicit modifier phases when modifier delay is configured."""

    device = _device(keyboard_modifier_delay=50)
    await device.keyboard_press("Control+Shift+s")

    combo = [c for c in fake_pyautogui.calls if c[0] in ("keyDown", "press", "keyUp")]
    assert [c[0] for c in combo] == [
        "keyDown",
        "keyDown",
        "press",
        "keyUp",
        "keyUp",
    ]
    assert [c[1] for c in combo] == [("ctrl",), ("shift",), ("s",), ("shift",), ("ctrl",)]
    assert not _calls(fake_pyautogui, "hotkey")


@pytest.mark.asyncio
async def test_keeps_the_existing_shortcut_path_when_modifier_delay_is_zero(
    fake_pyautogui,
):
    """keeps the existing shortcut path when modifier delay is zero."""

    device = _device(keyboard_modifier_delay=0)
    await device.keyboard_press("Control+s")

    assert _calls(fake_pyautogui, "hotkey")[0][1] == ("ctrl", "s")
    assert not _calls(fake_pyautogui, "keyDown")


@pytest.mark.asyncio
async def test_paces_the_select_all_shortcut_used_before_replacing_input(
    fake_pyautogui,
):
    """paces the select-all shortcut used before replacing input."""

    device = _device(keyboard_modifier_delay=50)
    await device.clear_input()

    assert not _calls(fake_pyautogui, "hotkey")
    assert [c[1] for c in _calls(fake_pyautogui, "keyDown")] == [("ctrl",)]
    presses = [c[1] for c in _calls(fake_pyautogui, "press")]
    assert presses == [("a",), ("backspace",)]
