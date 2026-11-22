"""Viewport parsing (upstream common/viewport.ts)."""

import math
from typing import Any, Dict, Optional, Union

DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 800
DEFAULT_VIEWPORT_SIZE: Dict[str, int] = {
    "width": DEFAULT_VIEWPORT_WIDTH,
    "height": DEFAULT_VIEWPORT_HEIGHT,
}
DEFAULT_PUPPETEER_WINDOW_VIEWPORT_SIZE: Dict[str, int] = {
    "width": DEFAULT_VIEWPORT_WIDTH,
    "height": DEFAULT_VIEWPORT_HEIGHT,
}
DEFAULT_STATIC_PAGE_VIEWPORT_SIZE: Dict[str, int] = {
    "width": DEFAULT_VIEWPORT_WIDTH,
    "height": DEFAULT_VIEWPORT_HEIGHT,
}


def _value_label(raw_value: Any) -> str:
    """Render a value the way JavaScript's string interpolation would."""
    if raw_value is None:
        return "null"
    if raw_value is True:
        return "true"
    if raw_value is False:
        return "false"
    return str(raw_value)


def _to_number(raw_value: Any) -> float:
    """Coerce like TypeScript ``typeof value === 'number' ? value : Number(value)``."""
    if isinstance(raw_value, bool):
        return 1.0 if raw_value else 0.0
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    try:
        return float(str(raw_value).strip())
    except (TypeError, ValueError):
        return math.nan


def parse_viewport_dimension(
    raw_value: Union[int, str, None],
    name: str,
) -> int:
    """Parse and validate a viewportWidth / viewportHeight option."""
    if raw_value is None:
        raise ValueError(f"{name} is required")
    parsed_value = _to_number(raw_value)
    if not math.isfinite(parsed_value) or parsed_value != int(parsed_value):
        raise ValueError(
            f"{name} must be a positive integer, but got {_value_label(raw_value)}"
        )
    if parsed_value <= 0:
        raise ValueError(
            f"{name} must be greater than 0, but got {_value_label(raw_value)}"
        )
    return int(parsed_value)


def resolve_viewport_size(
    viewport: Optional[Dict[str, Any]] = None,
    fallback: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Resolve ``{width, height}`` from numbers or strings."""
    resolved_fallback = fallback if fallback is not None else DEFAULT_VIEWPORT_SIZE
    width = (viewport or {}).get("width")
    height = (viewport or {}).get("height")
    return {
        "width": (
            resolved_fallback["width"]
            if width is None
            else parse_viewport_dimension(width, "viewportWidth")
        ),
        "height": (
            resolved_fallback["height"]
            if height is None
            else parse_viewport_dimension(height, "viewportHeight")
        ),
    }


def resolve_web_viewport_size(
    viewport: Optional[Dict[str, Any]] = None,
    fallback: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Resolve ``{width, height}`` from ``viewportWidth``/``viewportHeight``."""
    source = viewport or {}
    return resolve_viewport_size(
        {
            "width": source.get("viewportWidth"),
            "height": source.get("viewportHeight"),
        },
        fallback,
    )


def parse_viewport_size(config: Dict[str, Any]) -> Dict[str, int]:
    """Read a viewport size from a web target config."""
    return {
        "width": parse_viewport_dimension(
            config.get("viewportWidth"), "viewportWidth"
        ),
        "height": parse_viewport_dimension(
            config.get("viewportHeight"), "viewportHeight"
        ),
    }


__all__ = [
    "DEFAULT_PUPPETEER_WINDOW_VIEWPORT_SIZE",
    "DEFAULT_STATIC_PAGE_VIEWPORT_SIZE",
    "DEFAULT_VIEWPORT_HEIGHT",
    "DEFAULT_VIEWPORT_SIZE",
    "DEFAULT_VIEWPORT_WIDTH",
    "parse_viewport_dimension",
    "parse_viewport_size",
    "resolve_viewport_size",
    "resolve_web_viewport_size",
]
