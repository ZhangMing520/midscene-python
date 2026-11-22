"""Synced from upstream packages/core/tests/unit-test/mobile-scroll.test.ts."""

import pytest

from midscene.core.device.mobile_scroll import resolve_default_mobile_scroll

_SIZES = [
    {"width": 375, "height": 812},
    {"width": 812, "height": 375},
    {"width": 1024, "height": 1366},
]


@pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
def test_stays_centered_and_preserves_overlapping_travel_across_screen_sizes(direction):
    """%s stays centered and preserves overlapping travel across screen sizes"""
    for size in _SIZES:
        from_point, to_point = resolve_default_mobile_scroll(direction, size)
        from_point = list(from_point)
        to_point = list(to_point)
        horizontal = direction in ("left", "right")
        axis = 0 if horizontal else 1
        stationary = 1 if horizontal else 0
        extent = size["width"] if horizontal else size["height"]
        cross_extent = size["height"] if horizontal else size["width"]

        assert from_point[stationary] == round(cross_extent / 2)
        assert to_point[stationary] == from_point[stationary]
        assert abs(abs(to_point[axis] - from_point[axis]) - extent * 0.7) <= 1
        expected_sign = -1 if direction in ("down", "right") else 1
        assert (1 if to_point[axis] - from_point[axis] > 0 else -1) == expected_sign
        assert min(from_point[axis], to_point[axis]) > 0
        assert max(from_point[axis], to_point[axis]) < extent
