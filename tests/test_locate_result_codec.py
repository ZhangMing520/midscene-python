"""Synced from upstream packages/core/tests/unit-test/locate-result-codec.test.ts."""

import pytest

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_codec,
    resolve_bounds_type,
)


def test_preserves_closed_pixel_bounds_by_default():
    codec = create_locate_result_codec(
        {
            "resultKey": "bbox",
            "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
        }
    )
    result = codec.to_pixel_result(
        [100, 100, 199, 199], {"preparedSize": {"width": 320, "height": 240}}
    )

    # Closed bounds cover the final pixel: [100, 199] has 100 pixels and
    # its center is 150.
    assert result["center"] == (150, 150)
    rect = result["rect"]
    assert rect["left"] == 100 and rect["top"] == 100
    assert rect["width"] == 100 and rect["height"] == 100


def test_maps_normalized_bbox_values():
    codec = create_locate_result_codec(
        {
            "resultKey": "bbox_2d",
            "coordinates": {
                "shape": "bbox",
                "order": "xy",
                "normalizedBy": 1000,
                "rounding": "round",
            },
        }
    )

    # 500/1000 of 320 = 160 (closed interval [0, 160], center 80.5 -> 81),
    # 250/1000 of 240 = 60 (center 30.5 -> 31).
    result = codec.to_pixel_result(
        [0, 0, 500, 250], {"preparedSize": {"width": 320, "height": 240}}
    )

    assert result["center"] == (81, 31)


def test_supports_yx_point_responses_without_creating_a_rect():
    codec = create_locate_result_codec(
        {
            "resultKey": "point",
            "coordinates": {"shape": "point", "order": "yx", "rounding": "round"},
        }
    )

    result = codec.to_pixel_result(
        [30, 40], {"preparedSize": {"width": 320, "height": 240}}
    )

    assert result["center"] == (40, 30)
    assert result["rect"] is None


def test_qwen25_flexible_parser_accepts_bbox_and_point():
    from midscene.core.ai_model.models.registry import QWEN25_LOCATE_FORMAT

    codec = create_locate_result_codec(QWEN25_LOCATE_FORMAT)

    bbox_result = codec.to_pixel_result(
        [10, 10, 110, 60], {"preparedSize": {"width": 320, "height": 240}}
    )
    point_result = codec.to_pixel_result(
        [10, 10], {"preparedSize": {"width": 320, "height": 240}}
    )

    assert bbox_result["rect"] is not None
    assert point_result["center"] == (10, 10)
    assert point_result["rect"] is None


def test_rejects_actual_pixel_bbox_coordinates_outside_image_size():
    codec = create_locate_result_codec(
        {
            "resultKey": "bbox",
            "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
        }
    )

    with pytest.raises(ValueError):
        codec.to_pixel_result(
            [0, 0, 5000, 5000], {"preparedSize": {"width": 320, "height": 240}}
        )


def test_accepts_decimal_coordinate_strings():
    codec = create_locate_result_codec(
        {
            "resultKey": "bbox",
            "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
        }
    )

    result = codec.to_pixel_result(
        "100, 100, 199, 199", {"preparedSize": {"width": 320, "height": 240}}
    )

    assert result["center"] == (150, 150)


def test_clips_left_closed_right_open_boxes_independently_from_their_click_centers():
    from midscene.core.ai_model.models.registry import GPT_LOCATE_FORMAT

    codec = create_locate_result_codec(GPT_LOCATE_FORMAT)
    result = codec.to_pixel_result(
        [0, 0, 320, 240], {"preparedSize": {"width": 320, "height": 240}}
    )

    assert result["center"] == (160, 120)
    assert result["rect"]["width"] == 320
    assert result["rect"]["height"] == 240

    with pytest.raises(ValueError):
        codec.to_pixel_result(
            [0, 0, 321, 240], {"preparedSize": {"width": 320, "height": 240}}
        )


def test_closed_bbox_rejects_image_edges_and_aliases_resolve_to_the_same_bounds():
    from midscene.core.ai_model.models.registry import GPT_LOCATE_FORMAT

    codec = create_locate_result_codec(
        {
            "resultKey": "bbox",
            "coordinates": {
                "shape": "bbox",
                "order": "xy",
                "boundsType": "closed",
            },
        }
    )
    with pytest.raises(ValueError):
        codec.to_pixel_result(
            [0, 0, 320, 240], {"preparedSize": {"width": 320, "height": 240}}
        )

    # Legacy aliases resolve to the same canonical bounds.
    assert GPT_LOCATE_FORMAT["coordinates"]["boundsType"] == ("left-closed-right-open")


def test_resolves_bounds_type_aliases():
    assert resolve_bounds_type(None) == "closed"
    assert resolve_bounds_type("inclusive") == "closed"
    assert resolve_bounds_type("edges") == "left-closed-right-open"


def test_maps_normalized_coordinates_using_image_size_or_last_pixel_basis():
    def center_for(basis):
        codec = create_locate_result_codec(
            {
                "resultKey": "point",
                "coordinates": {
                    "shape": "point",
                    "normalizedBy": 1000,
                    "normalizationBasis": basis,
                },
            }
        )
        return codec.to_pixel_result(
            [900, 900], {"preparedSize": {"width": 320, "height": 240}}
        )["center"]

    # image-size maps 900/1000 to 288x216; last-pixel uses 319x239.
    assert center_for("image-size") == (288, 216)
    assert center_for("last-pixel") == (287, 215)
