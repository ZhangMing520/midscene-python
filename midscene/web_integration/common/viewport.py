"""Viewport parsing (upstream common/viewport.ts)."""

from typing import Any, Dict, Union

DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 800
DEFAULT_VIEWPORT_SIZE: Dict[str, int] = {
    "width": DEFAULT_VIEWPORT_WIDTH,
    "height": DEFAULT_VIEWPORT_HEIGHT,
}


def parse_viewport_dimension(
    raw_value: Union[int, str, None],
    name: str,
) -> int:
    """Parse and validate a viewportWidth / viewportHeight option."""
    if raw_value is None:
        raise ValueError(f"{name} is required")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be a positive integer") from e
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


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
    "DEFAULT_VIEWPORT_HEIGHT",
    "DEFAULT_VIEWPORT_SIZE",
    "DEFAULT_VIEWPORT_WIDTH",
    "parse_viewport_dimension",
    "parse_viewport_size",
]
