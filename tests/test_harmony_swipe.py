"""Port of upstream packages/harmony/tests/unit-test/swipe.test.ts."""

import math

import pytest

from midscene.harmony.swipe import resolve_swipe_speed


def test_converts_duration_to_speed_based_on_two_dimensional_distance():
    """converts duration to speed based on two-dimensional distance."""

    assert resolve_swipe_speed({"x": 0, "y": 0}, {"x": 300, "y": 400}, 1000) == 500


@pytest.mark.parametrize("duration,expected_speed", [(10000, 200), (1, 40000)])
def test_clamps_speed_to_hdc_limits_for_duration(duration, expected_speed):
    """clamps speed to HDC limits for duration $duration."""

    assert (
        resolve_swipe_speed({"x": 0, "y": 0}, {"x": 1000, "y": 0}, duration)
        == expected_speed
    )


@pytest.mark.parametrize("duration", [0, -1, math.nan, math.inf])
def test_rejects_invalid_duration(duration):
    """rejects invalid duration %s."""

    with pytest.raises(
        RuntimeError, match="Harmony swipe duration must be a positive finite number"
    ):
        resolve_swipe_speed({"x": 0, "y": 0}, {"x": 100, "y": 0}, duration)
