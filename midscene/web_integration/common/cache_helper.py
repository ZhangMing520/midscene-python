"""Locate-cache feature helpers (upstream common/cache-helper.ts)."""

from typing import Any, Callable, Dict, List, Optional

from midscene.core.ai_model.workflows.insight.order_sensitive import (
    resolve_order_sensitive,
)


def sanitize_xpaths(xpaths: Any) -> List[str]:
    """Keep only non-empty xpath strings from a cache feature payload."""
    if not isinstance(xpaths, list):
        return []
    return [
        xpath for xpath in xpaths if isinstance(xpath, str) and len(xpath) > 0
    ]


async def judge_order_sensitive(
    options: Optional[Dict[str, Any]] = None,
    debug: Optional[Callable[..., Any]] = None,
) -> bool:
    """Shared isOrderSensitive judgement for web cache features."""
    result = await resolve_order_sensitive(options)
    if debug is not None:
        debug("order sensitive", result)
    return result


def build_rect_from_element_info(element_info: Dict[str, Any]) -> Dict[str, Any]:
    """Copy an element's rect into a plain Rect mapping."""
    rect = element_info["rect"]
    return {
        "left": rect["left"],
        "top": rect["top"],
        "width": rect["width"],
        "height": rect["height"],
    }


__all__ = [
    "build_rect_from_element_info",
    "judge_order_sensitive",
    "sanitize_xpaths",
]
