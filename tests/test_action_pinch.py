"""Synced from upstream ``packages/core/tests/unit-test/action-pinch.test.ts``."""

from typing import Any, Dict, List

import pytest


def test_should_create_an_action_with_correct_name_and_alias():
    from midscene.core.device import build_web_action_space

    assert "Pinch" in [a.name for a in build_web_action_space()]


@pytest.mark.asyncio
async def test_should_reject_invalid_direction():
    from midscene.core.device import (
        build_web_action_space,
        find_action_in_action_space_or_throw,
    )

    class _PinchDevice:
        async def size(self):
            return {"width": 100, "height": 100}

        async def pinch(self, *args, **kwargs):
            pass

    definition = find_action_in_action_space_or_throw(
        "Pinch", build_web_action_space()
    )
    with pytest.raises(ValueError):
        await definition.execute({"direction": "sideways"}, _PinchDevice(), None)


class _RecordingPinchDevice:
    def __init__(self):
        self.calls: List[tuple] = []

    async def size(self) -> Dict[str, int]:
        return {"width": 1000, "height": 600}

    async def pinch(self, center, start_distance, end_distance, duration=None):
        self.calls.append((list(center), start_distance, end_distance, duration))


class TestPinchNormalization:
    def _normalize(self, param: Dict[str, Any]) -> Dict[str, Any]:
        from midscene.core.device import normalize_pinch_param

        return normalize_pinch_param(param, {"width": 1000, "height": 600})

    def test_defaults_and_outward_spread(self):
        assert self._normalize({"direction": "out"}) == {
            "center_x": 500,
            "center_y": 300,
            "start_distance": 150,
            "end_distance": 300,
            "duration": 500,
        }

    def test_locate_center_is_rounded(self):
        result = self._normalize(
            {"direction": "in", "locate": {"center": [10.4, 20.6]}}
        )
        assert (result["center_x"], result["center_y"]) == (10, 21)

    def test_inward_spread_keeps_a_minimum_gap(self):
        assert self._normalize({"direction": "in", "distance": 1000})[
            "end_distance"
        ] == 10

    def test_rejects_unknown_direction(self):
        with pytest.raises(ValueError, match="direction"):
            self._normalize({"direction": "sideways"})


    def test_android_action_space_includes_pinch(self):
        from midscene.core.device import build_action_space_for

        android = [a.name for a in build_action_space_for("android")]
        assert android.count("Pinch") == 1
        harmony = [a.name for a in build_action_space_for("harmony")]
        assert "Pinch" not in harmony


    @pytest.mark.asyncio
    async def test_executor_normalizes_and_forwards(self):
        from midscene.core.device import _execute_pinch

        device = _RecordingPinchDevice()
        await _execute_pinch(
            {
                "direction": "in",
                "locate": {"prompt": "a"},
                "distance": 100,
                "duration": 700,
            },
            device,
            _swipe_locate_fn,
        )
        assert device.calls == [([200, 150], 150, 50, 700)]



async def _swipe_locate_fn(locate):
    return {"center": {"a": (200, 150), "b": (200, -50)}[locate["prompt"]]}
