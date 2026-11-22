"""Pixel mapping helpers (upstream shared/model-locate-result)."""

from midscene.core.ai_model.shared.model_locate_result.pixel_mapper import (
    map_locate_result_to_pixel_rect,
    map_locate_result_to_unrounded_pixel_bbox,
    round_pixel_bbox,
)
from midscene.core.ai_model.shared.model_locate_result.types import (
    is_bbox_locate_result_value,
    is_point_locate_result_value,
)


def _bbox_result(coordinates, **meta):
    resolved = {
        "shape": "bbox",
        "order": "xy",
        "rounding": "round",
        "boundsType": "closed",
    }
    resolved.update(meta)
    return {"coordinates": coordinates, "coordinatesMeta": resolved}


def test_round_pixel_bbox_applies_each_rounding_policy():
    assert round_pixel_bbox([0.4, 1.5, 2.6, -1.5], "round") == [0, 2, 3, -1]
    assert round_pixel_bbox([1.9, 2.9, -1.9, 3.1], "trunc") == [1, 2, -1, 3]
    assert round_pixel_bbox([1.25, 2.5, 3.75, 4.5], "none") == [
        1.25,
        2.5,
        3.75,
        4.5,
    ]


def test_map_locate_result_to_pixel_rect_preserves_closed_interval_length():
    result = _bbox_result([100, 100, 199, 199])

    rect = map_locate_result_to_pixel_rect(
        result, {"preparedSize": {"width": 320, "height": 240}}
    )

    assert rect == {"left": 100, "top": 100, "width": 100, "height": 100}


def test_map_locate_result_to_pixel_rect_clips_to_content_size():
    result = _bbox_result(
        [-10, -10, 400, 300], boundsType="left-closed-right-open"
    )

    rect = map_locate_result_to_pixel_rect(
        result,
        {
            "preparedSize": {"width": 320, "height": 240},
            "contentSize": {"width": 300, "height": 200},
        },
    )

    assert rect == {"left": 0, "top": 0, "width": 300, "height": 200}


def test_map_unrounded_bbox_keeps_subpixel_precision_and_axis_order():
    result = _bbox_result(
        [250, 500, 750, 1000],
        order="yx",
        normalizedBy=1000,
        normalizationBasis="image-size",
    )

    bbox = map_locate_result_to_unrounded_pixel_bbox(
        result, {"width": 320, "height": 240}
    )

    assert bbox == [160.0, 60.0, 320.0, 180.0]


def test_locate_result_shape_guards():
    bbox = _bbox_result([0, 0, 10, 10])
    point = {
        "coordinates": [10, 20],
        "coordinatesMeta": {"shape": "point", "order": "xy", "rounding": "none"},
    }

    assert is_bbox_locate_result_value(bbox) is True
    assert is_point_locate_result_value(bbox) is False
    assert is_bbox_locate_result_value(point) is False
    assert is_point_locate_result_value(point) is True
