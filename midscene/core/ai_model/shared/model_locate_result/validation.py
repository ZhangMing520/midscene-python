"""Locate result validation (upstream shared/model-locate-result/validation.ts)."""

import math
from typing import Any

from midscene.core.ai_model.shared.model_locate_result.coordinates import (
    resolve_bounds_type,
    resolve_normalization_basis,
)


def assert_locate_result_structure(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValueError(
            f"invalid parsed locate result: expected object, got {result!r}"
        )

    coordinates_meta = result.get("coordinatesMeta") or {}
    shape = coordinates_meta.get("shape")
    if shape == "bbox":
        expected_length = 4
    elif shape == "point":
        expected_length = 2
    else:
        expected_length = 0
    if not expected_length:
        raise ValueError(
            f"invalid parsed locate result: unsupported coordinatesMeta.shape {shape!r}"
        )

    coordinates = result.get("coordinates")
    if (
        not isinstance(coordinates, (list, tuple))
        or len(coordinates) != expected_length
        or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in coordinates
        )
    ):
        raise ValueError(
            f"invalid parsed locate result: {shape} coordinates must be "
            f"{expected_length} finite numbers, got {coordinates!r}"
        )

    if shape == "bbox":
        resolve_bounds_type(coordinates_meta.get("boundsType"))

    rounding = coordinates_meta.get("rounding")
    if rounding not in ("round", "trunc", "none"):
        raise ValueError(f"invalid locate coordinate rounding: {rounding}")
    resolve_normalization_basis(coordinates_meta.get("normalizationBasis"))
    order = coordinates_meta.get("order")
    if order not in ("xy", "yx"):
        raise ValueError(f"invalid locate coordinate order: {order!r}")
    normalized_by = coordinates_meta.get("normalizedBy")
    if normalized_by is not None and (
        not math.isfinite(normalized_by) or normalized_by <= 0
    ):
        raise ValueError(
            f"locate result normalizedBy must be positive and finite: {normalized_by}"
        )


def _resolve_coordinate_limits(
    result: dict[str, Any], max_x: float, max_y: float
) -> list[float]:
    resolved = result["coordinatesMeta"]
    normalized_by = resolved.get("normalizedBy")
    if normalized_by is not None:
        return [normalized_by] * len(result["coordinates"])
    if resolved["shape"] == "bbox":
        if resolved["order"] == "yx":
            return [max_y, max_x, max_y, max_x]
        return [max_x, max_y, max_x, max_y]
    return [max_y, max_x] if resolved["order"] == "yx" else [max_x, max_y]


def assert_locate_result_coordinate_range_and_order(
    result: dict[str, Any], max_x: float, max_y: float
) -> None:
    coordinates_meta = result["coordinatesMeta"]
    normalized_by = coordinates_meta.get("normalizedBy")
    limits = _resolve_coordinate_limits(result, max_x, max_y)
    out_of_range = any(
        value < 0 or value > limits[index]
        for index, value in enumerate(result["coordinates"])
    )
    if out_of_range:
        source = (
            f"normalized range [0, {normalized_by}]"
            if normalized_by is not None
            else f"image size [0, {max_x}]x[0, {max_y}]"
        )
        normalized_info = (
            f" normalizedBy={normalized_by}" if normalized_by is not None else ""
        )
        raise ValueError(
            f"locate result coordinates {result['coordinates']!r} exceed {source}. "
            f"shape={coordinates_meta['shape']} order={coordinates_meta['order']}"
            f"{normalized_info} limits={limits!r}"
        )

    if coordinates_meta["shape"] == "bbox":
        coordinates = result["coordinates"]
        if coordinates[2] < coordinates[0] or coordinates[3] < coordinates[1]:
            raise ValueError(f"invalid locate bbox coordinate order: {coordinates!r}")
