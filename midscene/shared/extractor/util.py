"""Debug and geometry helpers for extraction (upstream extractor/util.ts).

The DOM-dependent helpers (getRect, elementRect, getNodeAttributes, ...) are
browser-only and have no Python SDK counterpart; only the platform-neutral
parts are ported here.
"""

from typing import Any, Dict, Optional

from loguru import logger as _logger

from midscene.shared.extractor.tree import truncate_text

MAX_VALUE_LENGTH = 300

_debug_mode = False


def set_debug_mode(mode: bool) -> None:
    global _debug_mode
    _debug_mode = mode


def get_debug_mode() -> bool:
    return _debug_mode


def logger(*msg: Any) -> None:
    """Print extraction diagnostics only when debug mode is on (upstream)."""
    if not _debug_mode:
        return
    _logger.debug(" ".join(str(part) for part in msg))


def overlapped_rect(
    rect1: Dict[str, float], rect2: Dict[str, float]
) -> Optional[Dict[str, float]]:
    """Intersection of two rects, or None when they do not overlap."""
    left = max(rect1["left"], rect2["left"])
    top = max(rect1["top"], rect2["top"])
    right = min(rect1["right"], rect2["right"])
    bottom = min(rect1["bottom"], rect2["bottom"])
    if left < right and top < bottom:
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left,
            "height": bottom - top,
            "x": left,
            "y": top,
            "zoom": 1,
        }
    return None


def is_element_partially_in_viewport(
    rect: Dict[str, float],
    viewport_width: float,
    viewport_height: float,
    visible_area_ratio: float = 2 / 3,
) -> bool:
    """True when enough of the element is inside the viewport (upstream)."""
    viewport_rect = {
        "left": 0,
        "top": 0,
        "right": viewport_width,
        "bottom": viewport_height,
        "width": viewport_width,
        "height": viewport_height,
        "x": 0,
        "y": 0,
        "zoom": 1,
    }
    overlap = overlapped_rect(rect, viewport_rect)
    if not overlap:
        return False
    total_area = rect["height"] * rect["width"]
    if total_area <= 0:
        return False
    return (overlap["width"] * overlap["height"]) / total_area >= visible_area_ratio


def trim_attribute_value(value: str) -> str:
    """Shorten image data URLs and oversized attribute values (upstream)."""
    if value.startswith("data:image"):
        return "image"
    if len(value) > MAX_VALUE_LENGTH:
        return f"{truncate_text(value, MAX_VALUE_LENGTH)}..."
    return value


__all__ = [
    "MAX_VALUE_LENGTH",
    "set_debug_mode",
    "get_debug_mode",
    "logger",
    "overlapped_rect",
    "is_element_partially_in_viewport",
    "trim_attribute_value",
]
