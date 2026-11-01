"""HarmonyOS swipe speed resolution (upstream swipe.ts)."""

import math
from typing import Dict

from .hdc import UI_INPUT_SPEED_RANGE

DEFAULT_SWIPE_DURATION_MS = 300


def resolve_swipe_speed(
    start: Dict[str, float], end: Dict[str, float],
    duration_ms: int = DEFAULT_SWIPE_DURATION_MS,
) -> int:
    """Convert a duration into the uitest px/s speed, clamped to the supported
    range (upstream resolveSwipeSpeed)."""
    if not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
        raise RuntimeError("Harmony swipe duration must be a positive finite number")

    distance = math.hypot(end["x"] - start["x"], end["y"] - start["y"])
    requested_speed = (distance * 1000) / duration_ms
    speed = min(
        UI_INPUT_SPEED_RANGE["max"],
        max(UI_INPUT_SPEED_RANGE["min"], requested_speed),
    )
    if speed != requested_speed:
        import math as _math

        logger = __import__("loguru").logger
        logger.warning(
            f"Harmony swipe speed {requested_speed}px/s was clamped to "
            f"{speed}px/s; the requested {duration_ms}ms duration cannot be "
            "represented exactly"
        )
        _ = _math  # keep import explicit
    return round(speed)
