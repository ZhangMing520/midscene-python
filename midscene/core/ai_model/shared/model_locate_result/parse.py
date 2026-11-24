"""Locate result value parsing (upstream shared/model-locate-result/parse.ts)."""

import math
from collections.abc import Sequence
from typing import Any


def unwrap_coordinate_list_like_input(
    coordinate_list: Any,
) -> list[Any] | str:
    if isinstance(coordinate_list, (list, tuple)):
        if coordinate_list and isinstance(coordinate_list[0], (list, tuple)):
            return list(coordinate_list[0])
        return list(coordinate_list)
    return str(coordinate_list)


def parse_coordinate_list(input_value: Any, label: str) -> list[float]:
    unwrapped = unwrap_coordinate_list_like_input(input_value)
    values: list[Any]
    if isinstance(unwrapped, str):
        values = [v for v in unwrapped.strip().split() if v]
        # split on whitespace; also handle comma-separated inside tokens
        expanded: list[str] = []
        for token in values:
            expanded.extend([t for t in token.split(",") if t])
        values = expanded
    else:
        values = unwrapped

    import re

    numeric_values: list[float] = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_values.append(float(value))
            continue
        if isinstance(value, str) and re.fullmatch(
            r"[+-]?(?:\d+\.?\d*|\.\d+)", value.strip()
        ):
            numeric_values.append(float(value))
        else:
            numeric_values.append(float("nan"))

    if not all(math.isfinite(v) for v in numeric_values):
        raise ValueError(f"invalid {label} data: {input_value!r} ")

    return numeric_values


def create_locate_result_value(
    coordinates_meta: dict[str, Any], coordinates: Sequence[float]
) -> dict[str, Any]:
    if coordinates_meta["shape"] == "point":
        return {
            "coordinates": [coordinates[0], coordinates[1]],
            "coordinatesMeta": coordinates_meta,
        }
    return {
        "coordinates": [
            coordinates[0],
            coordinates[1],
            coordinates[2],
            coordinates[3],
        ],
        "coordinatesMeta": coordinates_meta,
    }


def parse_numeric_locate_result(
    resolved_coordinates: dict[str, Any], input_value: Any
) -> dict[str, Any]:
    if resolved_coordinates["shape"] == "point":
        point = parse_coordinate_list(input_value, "point")
        if len(point) != 2:
            raise ValueError(f"invalid point data: {input_value!r} ")
        return create_locate_result_value(resolved_coordinates, point)

    bbox = parse_coordinate_list(input_value, "bbox")
    if len(bbox) != 4:
        raise ValueError(f"invalid bbox data: {input_value!r} ")
    return create_locate_result_value(resolved_coordinates, bbox)
