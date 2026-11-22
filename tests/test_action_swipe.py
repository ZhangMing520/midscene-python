"""Synced from upstream packages/core/tests/unit-test/action-swipe.test.ts and
device/swipe.test.ts."""

import pytest


def test_web_action_space_exposes_a_single_swipe_action():
    from midscene.core.device import build_action_space_for

    names = [action.name for action in build_action_space_for("web")]
    assert names.count("Swipe") == 1
    assert "Scroll" in names


def test_computer_action_space_keeps_one_swipe_action():
    from midscene.core.device import build_action_space_for

    names = [action.name for action in build_action_space_for("computer")]
    assert names.count("Swipe") == 1
    assert "Pinch" not in names


@pytest.mark.asyncio
async def test_forwards_duration_when_the_device_supports_it():
    from midscene.core.device import _execute_swipe

    class Device:
        def __init__(self):
            self.calls = []

        async def size(self):
            return {"width": 400, "height": 600}

        async def swipe(self, direction, distance=None, duration=None):
            self.calls.append((direction, distance, duration))

    device = Device()
    await _execute_swipe(
        {"direction": "up", "distance": 120, "duration": 900}, device, None
    )

    assert device.calls == [("up", 120, 900)]


@pytest.mark.asyncio
async def test_skips_duration_for_devices_without_the_keyword():
    from midscene.core.device import _execute_swipe

    class LegacyDevice:
        def __init__(self):
            self.calls = []

        async def size(self):
            return {"width": 400, "height": 600}

        async def swipe(self, direction, distance=None):
            self.calls.append((direction, distance))

    device = LegacyDevice()
    await _execute_swipe(
        {"direction": "left", "distance": 80, "duration": 900}, device, None
    )

    assert device.calls == [("left", 80)]
