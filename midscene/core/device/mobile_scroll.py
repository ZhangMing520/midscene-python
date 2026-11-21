"""Default untargeted mobile scroll gesture (upstream device/mobile-scroll.ts).

The finger crosses the central 70% of the axis opposite the requested content
direction, so consecutive observations keep overlapping content. Native
adapters own timing, coordinate conversion and gesture execution.
"""

import math
from typing import Dict, Tuple


def _round_half_up(value: float) -> int:
    # JS Math.round rounds half toward +infinity.
    return int(math.floor(value + 0.5))


def resolve_default_mobile_scroll(
    direction: str,
    size: Dict[str, int],
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return (from_point, to_point) for an untargeted scroll."""
    width, height = size["width"], size["height"]
    horizontal = direction in ("left", "right")
    forward = direction in ("down", "right")
    extent = width if horizontal else height
    start = _round_half_up(extent * (0.85 if forward else 0.15))
    end = _round_half_up(extent * (0.15 if forward else 0.85))
    from_point = [_round_half_up(width / 2), _round_half_up(height / 2)]
    to_point = list(from_point)
    if horizontal:
        from_point[0], to_point[0] = start, end
    else:
        from_point[1], to_point[1] = start, end
    return (from_point[0], from_point[1]), (to_point[0], to_point[1])
