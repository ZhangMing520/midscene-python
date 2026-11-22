"""Synced from upstream packages/core/tests/unit-test/action-swipe.test.ts and
device/swipe.test.ts."""

import pytest

from typing import Any, Dict, List


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


class _RecordingSwipeDevice:
    def __init__(self):
        self.points: List[tuple] = []
        self.direction_swipes: List[tuple] = []

    async def size(self) -> Dict[str, int]:
        return {"width": 1000, "height": 600}

    async def swipe(self, direction, distance=None, duration=None):
        self.direction_swipes.append((direction, distance, duration))

    async def swipe_points(self, start, end, duration=None):
        self.points.append((list(start), list(end), duration))


async def _swipe_locate_fn(locate):
    return {"center": {"a": (200, 150), "b": (200, -50)}[locate["prompt"]]}


class TestSwipeAction:
    def _normalize(self, param: Dict[str, Any]) -> Dict[str, Any]:
        from midscene.core.device import normalize_swipe_param

        return normalize_swipe_param(param, {"width": 1000, "height": 600})

    def test_relative_swipe_defaults_start_to_center(self):
        result = self._normalize({"direction": "up", "distance": 200})
        assert result["start_point"] == {"x": 500.0, "y": 300.0}
        assert result["end_point"] == {"x": 500.0, "y": 100.0}
        assert result["duration"] == 300
        assert result["repeat_count"] == 1

    def test_endpoint_swipe_clamps_to_screen(self):
        result = self._normalize(
            {"start": {"center": [200, 150]}, "end": {"center": [1200, -50]}}
        )
        assert result["start_point"] == {"x": 200.0, "y": 150.0}
        assert result["end_point"] == {"x": 1000.0, "y": 0.0}

    def test_end_cannot_combine_with_direction_or_distance(self):
        with pytest.raises(ValueError, match="cannot be combined"):
            self._normalize({"end": {"center": [1, 2]}, "direction": "up"})
        with pytest.raises(ValueError, match="cannot be combined"):
            self._normalize({"end": {"center": [1, 2]}, "distance": 10})

    def test_relative_swipe_requires_direction_and_distance(self):
        with pytest.raises(ValueError, match="relative swipe requires"):
            self._normalize({"direction": "up"})
        with pytest.raises(ValueError, match="relative swipe requires"):
            self._normalize({"distance": 10})
        with pytest.raises(ValueError, match="positive number"):
            self._normalize({"direction": "up", "distance": 0})

    def test_repeat_zero_means_capped_continuous_mode(self):
        assert (
            self._normalize({"direction": "up", "distance": 10, "repeat": 0})[
                "repeat_count"
            ]
            == 10
        )
        assert (
            self._normalize({"direction": "up", "distance": 10, "repeat": 3})[
                "repeat_count"
            ]
            == 3
        )
        with pytest.raises(ValueError, match="non-negative finite integer"):
            self._normalize({"direction": "up", "distance": 10, "repeat": 1.5})

    def test_swipe_action_exposes_endpoint_form(self):
        from midscene.core.device import _swipe_action

        action = _swipe_action()
        assert set(action.param_schema) == {
            "start", "direction", "distance", "end", "duration", "repeat"
        }
        assert action.locate_fields == ["start", "end"]
        assert "end" in action.description
        pointer = _swipe_action("pointer")
        assert pointer.param_schema["start"]["description"].startswith(
            "Optional starting point of the pointer movement"
        )

    @pytest.mark.asyncio
    async def test_executor_uses_swipe_points_for_endpoint_form(self):
        from midscene.core.device import _execute_swipe

        device = _RecordingSwipeDevice()
        await _execute_swipe(
            {
                "start": {"prompt": "a"},
                "end": {"prompt": "b"},
                "duration": 500,
                "repeat": 2,
            },
            device,
            _swipe_locate_fn,
        )
        assert device.points == [
            ([200.0, 150.0], [200.0, 0.0], 500),
            ([200.0, 150.0], [200.0, 0.0], 500),
        ]
        assert device.direction_swipes == []

    @pytest.mark.asyncio
    async def test_executor_keeps_direction_primitive_for_plain_relative_swipe(self):
        from midscene.core.device import _execute_swipe

        device = _RecordingSwipeDevice()
        await _execute_swipe(
            {"direction": "up", "distance": 200, "duration": 400},
            device,
            _swipe_locate_fn,
        )
        assert device.direction_swipes == [("up", 200, 400)]
        assert device.points == []
