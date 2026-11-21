"""Describe-service geometry and dump helpers.

Synced from upstream packages/core/src/service/utils.ts.
"""

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.shared.json import extract_json_from_code_block
from midscene.core.ai_model.workflows.grounding.search_area import (
    expand_search_area,
)

DESCRIBE_POINT_MARKER_MAX_SIZE = 40
DESCRIBE_RECT_MARKER_BORDER_THICKNESS = 1
DESCRIBE_LARGE_RECT_MARKER_BORDER_THICKNESS = 2
DESCRIBE_WIDE_MARKER_INSET_MIN_WIDTH = 100
_DESCRIBE_WIDE_MARKER_HORIZONTAL_INSET_RATIO = 0.15
_DESCRIBE_WIDE_MARKER_VERTICAL_INSET_RATIO = 0.1

# Deep describe uses an overview plus a focused crop. The overview keeps the
# original screenshot size; only focused crops may be upscaled.
DESCRIBE_DEEP_CONTEXT_CONFIG = {
    "resize": {
        "cropMaxLongEdge": 1000,
        "cropUpscaleMaxRatio": 2,
    }
}


def clamp_rect(rect: Dict[str, float], size: Dict[str, Any]) -> Dict[str, float]:
    """Clamp a rect into the image bounds."""
    width = min(float(rect["width"]), float(size["width"]))
    height = min(float(rect["height"]), float(size["height"]))
    return {
        "left": max(
            0.0, min(float(rect["left"]), float(size["width"]) - width)
        ),
        "top": max(
            0.0, min(float(rect["top"]), float(size["height"]) - height)
        ),
        "width": width,
        "height": height,
    }


def get_describe_deep_context_areas(
    rect: Dict[str, float], screen_size: Dict[str, Any]
) -> List[Dict[str, Any]]:
    return [
        {"kind": "focused", "rect": expand_search_area(rect, screen_size)}
    ]


def get_rect_in_crop(
    rect: Dict[str, float],
    crop_rect: Dict[str, float],
    crop_size: Dict[str, Any],
) -> Dict[str, float]:
    return clamp_rect(
        {
            "left": rect["left"] - crop_rect["left"],
            "top": rect["top"] - crop_rect["top"],
            "width": rect["width"],
            "height": rect["height"],
        },
        crop_size,
    )


def get_describe_marker_rect(rect: Dict[str, float]) -> Dict[str, float]:
    if rect["width"] < DESCRIBE_WIDE_MARKER_INSET_MIN_WIDTH:
        return rect

    horizontal_inset = round(
        rect["width"] * _DESCRIBE_WIDE_MARKER_HORIZONTAL_INSET_RATIO
    )
    vertical_inset = round(
        rect["height"] * _DESCRIBE_WIDE_MARKER_VERTICAL_INSET_RATIO
    )

    return {
        "left": rect["left"] + horizontal_inset,
        "top": rect["top"] + vertical_inset,
        "width": max(rect["width"] - horizontal_inset * 2, 1),
        "height": max(rect["height"] - vertical_inset * 2, 1),
    }


def get_describe_marker_border_thickness(rect: Dict[str, float]) -> int:
    if (
        rect["width"] <= DESCRIBE_POINT_MARKER_MAX_SIZE
        and rect["height"] <= DESCRIBE_POINT_MARKER_MAX_SIZE
    ):
        return DESCRIBE_RECT_MARKER_BORDER_THICKNESS
    return DESCRIBE_LARGE_RECT_MARKER_BORDER_THICKNESS


def get_describe_deep_locate_resize_size(
    size: Dict[str, Any]
) -> Optional[Dict[str, int]]:
    max_edge = max(float(size["width"]), float(size["height"]))
    if not max_edge:
        return None
    resize = DESCRIBE_DEEP_CONTEXT_CONFIG["resize"]
    scale = min(
        resize["cropUpscaleMaxRatio"], resize["cropMaxLongEdge"] / max_edge
    )
    if scale <= 1.05:
        return None
    return {
        "width": round(float(size["width"]) * scale),
        "height": round(float(size["height"]) * scale),
    }


def create_service_dump(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create one ServiceDump entry, filling log id and time."""
    return {
        "logId": uuid.uuid4().hex,
        "logTime": int(time.time() * 1000),
        **data,
    }


def _read_next_significant_char(
    value: str, start_index: int
) -> Optional[str]:
    index = start_index
    while index < len(value) and value[index].isspace():
        index += 1
    return value[index] if index < len(value) else None


def _extract_possibly_malformed_string_field(
    value: str, field_name: str
) -> Optional[str]:
    pattern = re.compile(
        rf'"{re.escape(field_name)}"\s*:\s*"'
    )
    field_start = pattern.search(value)
    if not field_start:
        return None

    index = field_start.end()
    escaped = False
    value_for_json_parse = ""

    while index < len(value):
        char = value[index]
        index += 1

        if escaped:
            value_for_json_parse += char
            escaped = False
            continue

        if char == "\\":
            value_for_json_parse += char
            escaped = True
            continue

        if char != '"':
            value_for_json_parse += char
            continue

        next_significant_char = _read_next_significant_char(value, index)
        if next_significant_char in (",", "}", "]", None):
            try:
                return json.loads(f'"{value_for_json_parse}"')
            except Exception:  # noqa: BLE001 - fall back to the raw text
                return value_for_json_parse

        value_for_json_parse += '\\"'

    return None


def recover_describe_response_from_parse_error(
    error: BaseException,
) -> Optional[Dict[str, str]]:
    """Recover a `description` from a malformed describe response."""
    message = str(error)
    if isinstance(error, AIResponseParseError):
        raw_response = error.raw_response
    else:
        match = re.search(r"Response -\s*\n\s*([\s\S]*)\Z", message)
        raw_response = match.group(1) if match else None

    if not raw_response or (
        "failed to parse LLM response into JSON" not in message
        and not isinstance(error, AIResponseParseError)
    ):
        return None

    json_like_response = extract_json_from_code_block(raw_response)
    description = _extract_possibly_malformed_string_field(
        json_like_response, "description"
    )
    description = description.strip() if description else ""
    if not description:
        return None
    return {"description": description}


__all__ = [
    "DESCRIBE_DEEP_CONTEXT_CONFIG",
    "DESCRIBE_LARGE_RECT_MARKER_BORDER_THICKNESS",
    "DESCRIBE_POINT_MARKER_MAX_SIZE",
    "DESCRIBE_RECT_MARKER_BORDER_THICKNESS",
    "DESCRIBE_WIDE_MARKER_INSET_MIN_WIDTH",
    "clamp_rect",
    "create_service_dump",
    "get_describe_deep_context_areas",
    "get_describe_deep_locate_resize_size",
    "get_describe_marker_border_thickness",
    "get_describe_marker_rect",
    "get_rect_in_crop",
    "recover_describe_response_from_parse_error",
]
