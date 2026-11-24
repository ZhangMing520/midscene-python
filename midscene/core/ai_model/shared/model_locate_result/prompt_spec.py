"""Prompt-facing describe helpers (upstream shared/model-locate-result/prompt-spec.ts)."""

from collections.abc import Sequence
from typing import Any


def format_locate_example_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    import json as _json

    return _json.dumps(value)


def describe_locate_result_coordinates(resolved: dict[str, Any]) -> str:
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


def describe_locate_result_value_schema(resolved: dict[str, Any]) -> str:
    return (
        "[number, number]"
        if resolved["shape"] == "point"
        else "[number, number, number, number]"
    )


def locate_result_example_value(
    resolved_coordinates: dict[str, Any], region: Sequence[float]
) -> list[float]:
    left, top, right, bottom = region
    if resolved_coordinates["shape"] == "point":
        x = round((left + right) / 2)
        y = round((top + bottom) / 2)
        return [y, x] if resolved_coordinates["order"] == "yx" else [x, y]
    if resolved_coordinates["order"] == "yx":
        return [top, left, bottom, right]
    return [left, top, right, bottom]


# Internal xy regions used only for prompt examples: [xmin, ymin, xmax, ymax]
LOCATE_RESULT_EXAMPLE_REGIONS: list[list[float]] = [
    [100, 100, 200, 200],
    [345, 442, 458, 483],
    [120, 180, 380, 210],
    [120, 240, 380, 270],
    [50, 100, 200, 200],
    [300, 400, 500, 500],
    [600, 100, 800, 250],
    [50, 600, 250, 750],
]


def locate_result_key(resolved: dict[str, Any]) -> str:
    return "point" if resolved["shape"] == "point" else "bbox"


def locate_result_name(resolved: dict[str, Any], plural: bool = False) -> str:
    if resolved["shape"] == "bbox":
        return "bounding boxes" if plural else "bounding box"
    return "points" if plural else "point"


def create_locate_result_prompt_spec(
    resolved_coordinates: dict[str, Any],
    result_key: str | None = None,
    result_key_aliases: list[str] | None = None,
) -> dict[str, Any]:
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
