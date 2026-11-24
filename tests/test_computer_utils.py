"""Port of upstream packages/computer/tests/unit-test/utils.test.ts."""

import asyncio

import pytest

from midscene.computer import utils as computer_utils
from midscene.computer.device import ComputerDevice
from midscene.computer.utils import (
    check_accessibility_permission,
    check_computer_environment,
    check_screen_recording_permission,
    get_connected_displays,
)


def test_version_is_exposed():
    assert isinstance(computer_utils.version(), str)


def test_permission_checks_are_granted_off_darwin(monkeypatch):
    monkeypatch.setattr(computer_utils, "_platform_name", lambda: "linux")

    assert check_accessibility_permission() == {
        "hasPermission": True,
        "platform": "linux",
    }
    assert check_screen_recording_permission() == {
        "hasPermission": True,
        "platform": "linux",
    }


def test_get_connected_displays_delegates_to_the_device(monkeypatch):
    displays = [{"id": "0", "name": "Display 0", "primary": True}]

    async def fake_list_displays():
        return displays

    monkeypatch.setattr(
        ComputerDevice, "list_displays", staticmethod(fake_list_displays)
    )

    assert asyncio.run(get_connected_displays()) == displays


def test_check_computer_environment_reports_unavailable_without_screen(monkeypatch):
    async def broken_pyautogui():
        raise RuntimeError("no display")

    monkeypatch.setattr(
        "midscene.computer.input_driver.load_pyautogui", broken_pyautogui
    )
    monkeypatch.setattr(computer_utils, "_platform_name", lambda: "linux")

    result = asyncio.run(check_computer_environment())

    assert result["available"] is False
    assert result["error"] == "no display"
    assert result["platform"] == "linux"
    assert result["displays"] == 0


@pytest.mark.skip(
    reason=(
        "checkComputerEnvironment requires a real pyautogui screen backend; "
        "the unavailable branch is covered with an injected failure"
    )
)
def test_check_computer_environment_reports_available_on_a_desktop():
    result = asyncio.run(check_computer_environment())
    assert result["available"] is True
