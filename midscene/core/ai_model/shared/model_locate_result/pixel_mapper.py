"""Pixel coordinate mapping (upstream shared/model-locate-result/pixel-mapper.ts)."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from midscene.core.ai_model.shared.model_locate_result.coordinates import (
    resolve_bounds_type,
    resolve_normalization_basis,
)
from midscene.core.ai_model.shared.model_locate_result.types import (
    BboxBoundsType,
    CoordinateRounding,
    NormalizationBasis,
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def max_pixel_coordinate(size: float) -> float:
    return max(size - 1, 0)


def normalized_coordinate_to_pixel(
    value: float,
    normalized_by: float,
    size: float,
    normalization_basis: NormalizationBasis = "image-size",
) -> float:
    """Convert units without rounding, retaining intermediate precision."""
    basis = resolve_normalization_basis(normalization_basis)
    scale = size if basis == "image-size" else max_pixel_coordinate(size)
    return (value * scale) / normalized_by


def round_pixel_coordinate(pixel: float, rounding: CoordinateRounding) -> float:
    if rounding == "round":
        # JS Math.round semantics (half up), unlike Python's banker's rounding.
        return math.floor(pixel + 0.5)
    if rounding == "trunc":
        return math.trunc(pixel)
    if rounding == "none":
        return pixel
    raise ValueError(f"Invalid coordinate rounding: {rounding}")


def clamp_pixel_point_to_size(
    point: Sequence[float], size: Mapping[str, float]
) -> tuple[float, float]:
    x, y = point
    return (
        _clamp(x, 0, max_pixel_coordinate(size["width"])),
        _clamp(y, 0, max_pixel_coordinate(size["height"])),
    )


def clamp_pixel_bbox_to_size(
    pixel_bbox: Sequence[float],
    size: Mapping[str, float],
    bounds_type: BboxBoundsType = "closed",
) -> list[float]:
    left, top, right, bottom = pixel_bbox
    if resolve_bounds_type(bounds_type) == "left-closed-right-open":
        return [
            _clamp(left, 0, size["width"]),
            _clamp(top, 0, size["height"]),
            _clamp(right, 0, size["width"]),
            _clamp(bottom, 0, size["height"]),
        ]
    tl = clamp_pixel_point_to_size([left, top], size)
    br = clamp_pixel_point_to_size([right, bottom], size)
    return [tl[0], tl[1], br[0], br[1]]


def pixel_interval_length(
    start: float, end: float, bounds_type: BboxBoundsType = "closed"
) -> float:
    return end - start + (1 if resolve_bounds_type(bounds_type) == "closed" else 0)


def pixel_interval_center(
    start: float,
    end: float,
    bounds_type: BboxBoundsType,
    rounding: CoordinateRounding,
) -> float:
    center = round_pixel_coordinate(
        start + pixel_interval_length(start, end, bounds_type) / 2,
        rounding,
    )
    if rounding == "none":
        return center

    minimum = math.ceil(start)
    maximum = (
        math.floor(end)
        if resolve_bounds_type(bounds_type) == "closed"
        else math.ceil(end) - 1
    )
    # No integer satisfies the interval; keep the configured approximation.
    return center if minimum > maximum else _clamp(center, minimum, maximum)


def pixel_bbox_to_rect(
    pixel_bbox: Sequence[float], bounds_type: BboxBoundsType = "closed"
) -> dict[str, float]:
    left, top, right, bottom = pixel_bbox
    return {
        "left": left,
        "top": top,
        "width": pixel_interval_length(left, right, bounds_type),
        "height": pixel_interval_length(top, bottom, bounds_type),
    }


def round_pixel_bbox(
    pixel_bbox: Sequence[float],
    rounding: CoordinateRounding,
) -> list[float]:
    """Round all four bbox endpoints with the configured policy."""
    return [round_pixel_coordinate(value, rounding) for value in pixel_bbox]


def map_locate_result_to_unrounded_pixel_bbox(
    result: dict[str, Any], size: Mapping[str, float]
) -> list[float]:
    meta = result["coordinatesMeta"]
    normalized_by = meta.get("normalizedBy")
    order = meta["order"]
    first, second, third, fourth = result["coordinates"]
    xy_bbox: list[float] = (
        [second, first, fourth, third] if order == "yx" else list(result["coordinates"])
    )
    if normalized_by is None:
        return xy_bbox
    basis = resolve_normalization_basis(meta.get("normalizationBasis"))
    return [
        normalized_coordinate_to_pixel(xy_bbox[0], normalized_by, size["width"], basis),
        normalized_coordinate_to_pixel(
            xy_bbox[1], normalized_by, size["height"], basis
        ),
        normalized_coordinate_to_pixel(xy_bbox[2], normalized_by, size["width"], basis),
        normalized_coordinate_to_pixel(
            xy_bbox[3], normalized_by, size["height"], basis
        ),
    ]


def map_locate_result_to_pixel_bbox(
    result: dict[str, Any], size: Mapping[str, float]
) -> list[float]:
    rounding = result["coordinatesMeta"]["rounding"]
    return round_pixel_bbox(
        map_locate_result_to_unrounded_pixel_bbox(result, size), rounding
    )


def map_locate_result_to_pixel_rect(
    result: dict[str, Any], context: dict[str, dict[str, float]]
) -> dict[str, float]:
    """Build the original bbox rect independently from the click center."""
    prepared_size = context["preparedSize"]
    content_size = context.get("contentSize") or prepared_size
    meta = result["coordinatesMeta"]
    rounding = meta["rounding"]
    bounds_type = resolve_bounds_type(meta.get("boundsType"))
    left, top, right, bottom = clamp_pixel_bbox_to_size(
        round_pixel_bbox(
            map_locate_result_to_unrounded_pixel_bbox(result, prepared_size),
            rounding,
        ),
        content_size,
        bounds_type,
    )
    return {
        "left": left,
        "top": top,
        "width": pixel_interval_length(left, right, bounds_type),
        "height": pixel_interval_length(top, bottom, bounds_type),
    }


def map_locate_result_to_pixel_point(
    result: dict[str, Any], size: Mapping[str, float]
) -> tuple[float, float]:
    meta = result["coordinatesMeta"]
    order = meta["order"]
    normalized_by = meta.get("normalizedBy")
    rounding = meta["rounding"]
    if meta["shape"] == "bbox":
        left, top, right, bottom = map_locate_result_to_unrounded_pixel_bbox(
            result, size
        )
        bounds_type = resolve_bounds_type(meta.get("boundsType"))
        return (
            pixel_interval_center(left, right, bounds_type, rounding),
            pixel_interval_center(top, bottom, bounds_type, rounding),
        )
    first, second = result["coordinates"]
    x, y = (second, first) if order == "yx" else (first, second)
    if normalized_by is None:
        return (x, y)
    basis = resolve_normalization_basis(meta.get("normalizationBasis"))
    return (
        round_pixel_coordinate(
            normalized_coordinate_to_pixel(x, normalized_by, size["width"], basis),
            rounding,
        ),
        round_pixel_coordinate(
            normalized_coordinate_to_pixel(y, normalized_by, size["height"], basis),
            rounding,
        ),
    )
