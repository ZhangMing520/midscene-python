"""
Locate result parsing, validation and coordinate mapping.

Synced from upstream web-infra-dev/midscene v1.17.4:
  packages/core/src/ai-model/shared/model-locate-result/*
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .env_config import (
    planning_model_family_required_for_locate_message,  # noqa: F401 (re-export)
)

Bbox = List[float]  # [xmin, ymin, xmax, ymax] after order normalization
LocateResultBbox = Bbox
PixelBbox = Bbox
LocateResultPoint = Tuple[float, float]

CoordinateRounding = str  # 'round' | 'trunc' | 'none'
BboxBoundsType = str  # 'inclusive' | 'edges'


def format_locate_example_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    import json as _json

    return _json.dumps(value)


def describe_locate_result_coordinates(resolved: Dict[str, Any]) -> str:
    shape = resolved["shape"]
    order = resolved["order"]
    normalized_by = resolved.get("normalizedBy")
    descriptor = "point" if shape == "point" else "2d bounding box"
    if normalized_by is not None:
        coordinate_description = (
            f"normalized to 0-{normalized_by} relative to the screenshot. "
            "Do NOT use pixel coordinates or screenshot width/height"
        )
    else:
        coordinate_description = (
            "in actual pixel coordinates relative to the screenshot"
        )
    if shape == "point":
        order_description = "[y, x]" if order == "yx" else "[x, y]"
        return f"{descriptor}, should be {order_description} {coordinate_description}."
    order_description = (
        "[ymin, xmin, ymax, xmax]" if order == "yx" else "[xmin, ymin, xmax, ymax]"
    )
    return f"{descriptor}, should be {order_description} {coordinate_description}."


def describe_locate_result_value_schema(resolved: Dict[str, Any]) -> str:
    return (
        "[number, number]"
        if resolved["shape"] == "point"
        else "[number, number, number, number]"
    )


def locate_result_example_value(
    resolved_coordinates: Dict[str, Any], region: Sequence[float]
) -> List[float]:
    left, top, right, bottom = region
    if resolved_coordinates["shape"] == "point":
        x = round((left + right) / 2)
        y = round((top + bottom) / 2)
        return [y, x] if resolved_coordinates["order"] == "yx" else [x, y]
    if resolved_coordinates["order"] == "yx":
        return [top, left, bottom, right]
    return [left, top, right, bottom]


# Internal xy regions used only for prompt examples: [xmin, ymin, xmax, ymax]
LOCATE_RESULT_EXAMPLE_REGIONS: List[List[float]] = [
    [100, 100, 200, 200],
    [345, 442, 458, 483],
    [120, 180, 380, 210],
    [120, 240, 380, 270],
    [50, 100, 200, 200],
    [300, 400, 500, 500],
    [600, 100, 800, 250],
    [50, 600, 250, 750],
]


def locate_result_key(resolved: Dict[str, Any]) -> str:
    return "point" if resolved["shape"] == "point" else "bbox"


def locate_result_name(resolved: Dict[str, Any], plural: bool = False) -> str:
    if resolved["shape"] == "bbox":
        return "bounding boxes" if plural else "bounding box"
    return "points" if plural else "point"


def create_locate_result_prompt_spec(
    resolved_coordinates: Dict[str, Any],
    result_key: Optional[str] = None,
    result_key_aliases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "resultKey": result_key or locate_result_key(resolved_coordinates),
        "resultKeyAliases": result_key_aliases or [],
        "resultValueSchema": describe_locate_result_value_schema(resolved_coordinates),
        "resultValueDescription": describe_locate_result_coordinates(
            resolved_coordinates
        ),
        "resultNoun": locate_result_name(resolved_coordinates),
        "resultNounPlural": locate_result_name(resolved_coordinates, plural=True),
        "exampleValues": [
            locate_result_example_value(resolved_coordinates, region)
            for region in LOCATE_RESULT_EXAMPLE_REGIONS
        ],
    }


# ---------------------------------------------------------------------------
# Parsing (parse.ts)
# ---------------------------------------------------------------------------

def unwrap_coordinate_list_like_input(
    coordinate_list: Any,
) -> Union[List[Any], str]:
    if isinstance(coordinate_list, (list, tuple)):
        if coordinate_list and isinstance(coordinate_list[0], (list, tuple)):
            return list(coordinate_list[0])
        return list(coordinate_list)
    return str(coordinate_list)


def parse_coordinate_list(input_value: Any, label: str) -> List[float]:
    unwrapped = unwrap_coordinate_list_like_input(input_value)
    if isinstance(unwrapped, str):
        values = [v for v in unwrapped.strip().split() if v]
        # split on whitespace; also handle comma-separated inside tokens
        expanded: List[str] = []
        for token in values:
            expanded.extend([t for t in token.split(",") if t])
        values = expanded
    else:
        values = unwrapped

    if not isinstance(values, (list, tuple)):
        raise ValueError(f"invalid {label} data: {input_value!r} ")

    import re

    numeric_values: List[float] = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_values.append(float(value))
            continue
        if (
            isinstance(value, str)
            and re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)", value.strip())
        ):
            numeric_values.append(float(value))
        else:
            numeric_values.append(float("nan"))

    if not all(math.isfinite(v) for v in numeric_values):
        raise ValueError(f"invalid {label} data: {input_value!r} ")

    return numeric_values


def create_locate_result_value(
    coordinates_meta: Dict[str, Any], coordinates: Sequence[float]
) -> Dict[str, Any]:
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
    resolved_coordinates: Dict[str, Any], input_value: Any
) -> Dict[str, Any]:
    if resolved_coordinates["shape"] == "point":
        point = parse_coordinate_list(input_value, "point")
        if len(point) != 2:
            raise ValueError(f"invalid point data: {input_value!r} ")
        return create_locate_result_value(resolved_coordinates, point)

    bbox = parse_coordinate_list(input_value, "bbox")
    if len(bbox) != 4:
        raise ValueError(f"invalid bbox data: {input_value!r} ")
    return create_locate_result_value(resolved_coordinates, bbox)


# ---------------------------------------------------------------------------
# Validation (validation.ts)
# ---------------------------------------------------------------------------

def assert_locate_result_structure(result: Dict[str, Any]) -> None:
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
            "invalid parsed locate result: unsupported coordinatesMeta.shape "
            f"{shape!r}"
        )

    coordinates = result.get("coordinates")
    if (
        not isinstance(coordinates, (list, tuple))
        or len(coordinates) != expected_length
        or not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            for v in coordinates
        )
    ):
        raise ValueError(
            f"invalid parsed locate result: {shape} coordinates must be "
            f"{expected_length} finite numbers, got {coordinates!r}"
        )

    if shape == "bbox":
        bounds_type = coordinates_meta.get("boundsType")
        if bounds_type is not None and bounds_type not in ("inclusive", "edges"):
            raise ValueError(f"invalid locate bbox boundsType: {bounds_type}")

    rounding = coordinates_meta.get("rounding")
    if rounding not in ("round", "trunc", "none"):
        raise ValueError(f"invalid locate coordinate rounding: {rounding}")
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
    result: Dict[str, Any], max_x: float, max_y: float
) -> List[float]:
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
    result: Dict[str, Any], max_x: float, max_y: float
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
            raise ValueError(
                f"invalid locate bbox coordinate order: {coordinates!r}"
            )


# ---------------------------------------------------------------------------
# Pixel mapping (pixel-mapper.ts)
# ---------------------------------------------------------------------------

def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def max_pixel_coordinate(size: float) -> float:
    return max(size - 1, 0)


def normalized_coordinate_to_pixel(
    value: float,
    normalized_by: float,
    size: float,
    rounding: CoordinateRounding,
) -> float:
    pixel = (value * size) / normalized_by
    if rounding == "round":
        return round(pixel)
    if rounding == "trunc":
        return math.trunc(pixel)
    if rounding == "none":
        return pixel
    raise ValueError(f"Invalid coordinate rounding: {rounding}")


def clamp_pixel_point_to_size(
    point: Sequence[float], size: Dict[str, float]
) -> Tuple[float, float]:
    x, y = point
    return (
        _clamp(x, 0, max_pixel_coordinate(size["width"])),
        _clamp(y, 0, max_pixel_coordinate(size["height"])),
    )


def clamp_pixel_bbox_to_size(
    pixel_bbox: Sequence[float],
    size: Dict[str, float],
    bounds_type: BboxBoundsType = "inclusive",
) -> List[float]:
    left, top, right, bottom = pixel_bbox
    if bounds_type == "edges":
        return [
            _clamp(left, 0, size["width"]),
            _clamp(top, 0, size["height"]),
            _clamp(right, 0, size["width"]),
            _clamp(bottom, 0, size["height"]),
        ]
    tl = clamp_pixel_point_to_size([left, top], size)
    br = clamp_pixel_point_to_size([right, bottom], size)
    return [tl[0], tl[1], br[0], br[1]]


def pixel_bbox_to_rect(
    pixel_bbox: Sequence[float], bounds_type: BboxBoundsType = "inclusive"
) -> Dict[str, float]:
    left, top, right, bottom = pixel_bbox
    extra = 1 if bounds_type == "inclusive" else 0
    return {
        "left": left,
        "top": top,
        "width": right - left + extra,
        "height": bottom - top + extra,
    }


def map_locate_result_to_pixel_bbox(
    result: Dict[str, Any], size: Dict[str, float]
) -> List[float]:
    meta = result["coordinatesMeta"]
    normalized_by = meta.get("normalizedBy")
    order = meta["order"]
    rounding = meta["rounding"]
    first, second, third, fourth = result["coordinates"]
    xy_bbox: List[float] = (
        [second, first, fourth, third] if order == "yx" else list(result["coordinates"])
    )
    if normalized_by is None:
        return xy_bbox
    return [
        normalized_coordinate_to_pixel(xy_bbox[0], normalized_by, size["width"], rounding),
        normalized_coordinate_to_pixel(xy_bbox[1], normalized_by, size["height"], rounding),
        normalized_coordinate_to_pixel(xy_bbox[2], normalized_by, size["width"], rounding),
        normalized_coordinate_to_pixel(xy_bbox[3], normalized_by, size["height"], rounding),
    ]


def map_locate_result_to_pixel_point(
    result: Dict[str, Any], size: Dict[str, float]
) -> Tuple[float, float]:
    meta = result["coordinatesMeta"]
    order = meta["order"]
    normalized_by = meta.get("normalizedBy")
    rounding = meta["rounding"]
    if meta["shape"] == "bbox":
        first = (result["coordinates"][0] + result["coordinates"][2]) / 2
        second = (result["coordinates"][1] + result["coordinates"][3]) / 2
    else:
        first, second = result["coordinates"]
    x, y = (second, first) if order == "yx" else (first, second)
    if normalized_by is None:
        return (x, y)
    return (
        normalized_coordinate_to_pixel(x, normalized_by, size["width"], rounding),
        normalized_coordinate_to_pixel(y, normalized_by, size["height"], rounding),
    )


def create_coordinate_distance_to_pixels(
    size: Dict[str, float], coordinate_system: Dict[str, Any]
):
    def distance_to_pixels(delta: float, axis: str) -> float:
        if coordinate_system.get("normalizedBy") is None:
            return round(abs(delta))
        length = size["width"] if axis == "x" else size["height"]
        return normalized_coordinate_to_pixel(
            abs(delta),
            coordinate_system["normalizedBy"],
            length,
            coordinate_system["rounding"],
        )

    return distance_to_pixels


# ---------------------------------------------------------------------------
# Codec factory (factory.ts)
# ---------------------------------------------------------------------------

def resolve_locate_result_coordinates(coordinates: Dict[str, Any]) -> Dict[str, Any]:
    normalized_by = coordinates.get("normalizedBy")
    if normalized_by is not None and normalized_by <= 0:
        raise ValueError(
            f"locate result coordinates normalizedBy must be positive: {normalized_by}"
        )
    resolved: Dict[str, Any] = {
        "shape": coordinates["shape"],
        "order": coordinates.get("order") or "xy",
        "normalizedBy": normalized_by,
        "rounding": coordinates.get("rounding") or "round",
    }
    if coordinates["shape"] == "bbox":
        resolved["boundsType"] = coordinates.get("boundsType") or "inclusive"
    return resolved


class LocateResultCodec:
    """Parse a raw locate value once and map it to {center, rect} pixels."""

    def __init__(
        self,
        prompt_spec: Dict[str, Any],
        resolved_coordinates: Dict[str, Any],
        parse_raw_locate_value=None,
    ):
        self.prompt_spec = prompt_spec
        self._resolved_coordinates = resolved_coordinates
        self._parse_raw_locate_value = parse_raw_locate_value or (
            lambda raw: parse_numeric_locate_result(resolved_coordinates, raw)
        )

    def to_pixel_result(
        self,
        raw_result: Any,
        context: Dict[str, Dict[str, float]],
    ) -> Dict[str, Any]:
        """Return {center, rect?}; rect is None for point results."""
        result = self._parse_raw_locate_value(raw_result)
        prepared_size = context["preparedSize"]
        content_size = context.get("contentSize") or prepared_size
        assert_locate_result_structure(result)
        edge_bounds = (
            result["coordinatesMeta"]["shape"] == "bbox"
            and result["coordinatesMeta"].get("boundsType") == "edges"
        )
        assert_locate_result_coordinate_range_and_order(
            result,
            prepared_size["width"] - (0 if edge_bounds else 1),
            prepared_size["height"] - (0 if edge_bounds else 1),
        )
        center = clamp_pixel_point_to_size(
            map_locate_result_to_pixel_point(result, prepared_size), content_size
        )
        rect: Optional[Dict[str, float]] = None
        if result["coordinatesMeta"]["shape"] == "bbox":
            pixel_bbox = clamp_pixel_bbox_to_size(
                map_locate_result_to_pixel_bbox(result, prepared_size),
                content_size,
                result["coordinatesMeta"].get("boundsType", "inclusive"),
            )
            rect = pixel_bbox_to_rect(
                pixel_bbox, result["coordinatesMeta"].get("boundsType", "inclusive")
            )
        return {"center": center, "rect": rect}


def create_locate_result_codec(
    result_format: Dict[str, Any],
) -> LocateResultCodec:
    """Create a codec from a LocateResultFormatDefinition:
    {resultKey?, resultKeyAliases?, coordinates, parseRawLocateValue?}."""
    resolved = resolve_locate_result_coordinates(result_format["coordinates"])
    prompt_spec = create_locate_result_prompt_spec(
        resolved,
        result_key=result_format.get("resultKey"),
        result_key_aliases=result_format.get("resultKeyAliases"),
    )
    return LocateResultCodec(
        prompt_spec=prompt_spec,
        resolved_coordinates=resolved,
        parse_raw_locate_value=result_format.get("parseRawLocateValue"),
    )


def locate_result_keys(prompt_spec: Dict[str, Any]) -> List[str]:
    return [prompt_spec["resultKey"], *prompt_spec.get("resultKeyAliases", [])]


def read_locate_result_field(
    record: Dict[str, Any], prompt_spec: Dict[str, Any], prefix: str = ""
) -> Any:
    """An explicit null or empty array takes precedence over any fallback field."""
    for key in locate_result_keys(prompt_spec):
        full_key = f"{prefix}{key}"
        if full_key in record and record[full_key] is not None:
            return record[full_key]
    return None
