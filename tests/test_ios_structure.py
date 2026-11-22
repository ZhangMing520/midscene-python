"""Port of upstream packages/ios/tests/unit-test/structure.test.ts.

Only the ``IOSDevice`` structure cases covered by the former aggregate
``tests/test_ios.py`` are kept: the Node-only WDAManager, ``describe()`` and
custom-action plumbing have no Python counterpart.
"""

from midscene.core.device import build_action_space_for
from midscene.ios.device import IOSDevice


def test_should_have_correct_interface_type():
    """should have correct interface type."""

    device = IOSDevice()
    assert device.interface_type.value == "ios"


def test_should_have_proper_action_space():
    """should have proper action space."""

    actions = build_action_space_for("ios")
    names = [action.name for action in actions]

    assert isinstance(names, list)
    assert len(names) > 0
    assert "Tap" in names
    assert "Input" in names
    assert "Scroll" in names
    assert "IOSHomeButton" in names
    assert "LongPress" in names
    assert "Swipe" in names
    assert "IOSAppSwitcher" in names
    # iOS has no mouse buttons.
    assert "RightClick" not in names
