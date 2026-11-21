"""UI coordinate helpers (upstream agent/ui-utils.ts)."""

from typing import Any, Dict

from midscene.core.types import UIContext


def to_logical_coords(element: Dict[str, Any], context: UIContext) -> Dict[str, Any]:
    """Scale screenshot-space coordinates back to logical viewport space
    (upstream task-builder.ts divides the shot coordinates by
    shrunkShotToLogicalRatio)."""
    ratio = float(getattr(context, "shrunk_shot_to_logical_ratio", 1.0) or 1.0)
    if ratio == 1.0:
        return element
    center = element.get("center")
    if center:
        element = {
            **element,
            "center": [center[0] / ratio, center[1] / ratio],
        }
    rect = element.get("rect")
    if rect:
        element = {
            **element,
            "rect": {
                "left": rect["left"] / ratio,
                "top": rect["top"] / ratio,
                "width": rect["width"] / ratio,
                "height": rect["height"] / ratio,
            },
        }
    return element
