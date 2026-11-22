"""Port of upstream packages/computer/tests/unit-test/device.test.ts.

Only the cases covered by the former aggregate ``tests/test_computer.py`` are
kept. The Python backend captures with pyautogui, so upstream's multi-display
selection has no equivalent and the case is skipped with that reason.
"""

import pytest

from midscene.computer.device import ComputerDevice
from midscene.core.device import build_action_space_for


def test_should_have_action_space():
    """should have action space."""

    device = ComputerDevice()
    actions = build_action_space_for(device.interface_type.value)
    action_names = [action.name for action in actions]

    assert len(action_names) > 0
    assert "Tap" in action_names
    assert "Input" in action_names
    assert "Scroll" in action_names
    assert "KeyboardPress" in action_names
    # Mouse actions, including Hover (aiHover) — see issue #2413
    assert "Hover" in action_names
    assert "DoubleClick" in action_names
    assert "RightClick" in action_names
    assert "MiddleClick" in action_names
    assert "DragAndDrop" in action_names
    assert "Swipe" in action_names
    # The desktop backend has no two-finger touch surface.
    assert "Pinch" not in action_names


@pytest.mark.skip(
    reason=(
        "Python's pyautogui backend captures the primary display only and "
        "ComputerDevice rejects display_id with NotImplementedError"
    )
)
def test_should_create_device_with_display_id():
    """should create device with display id."""

    ComputerDevice(display_id="test-display")
