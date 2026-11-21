"""Search-area coordinate mapping (upstream workflows/grounding/search-area-mapping.ts)."""

from typing import Any, Dict, List, Optional, Sequence


def map_search_area_point_to_original_point(
    point: Sequence[float], mapping: Optional[Dict[str, Any]] = None
) -> List[float]:
    scale = (mapping or {}).get("scale", 1)
    offset = (mapping or {}).get("offset", {"x": 0, "y": 0})
    return [point[0] / scale + offset["x"], point[1] / scale + offset["y"]]


def map_search_area_rect_to_original_rect(
    rect: Dict[str, float], mapping: Optional[Dict[str, Any]] = None
) -> Dict[str, float]:
    left, top = map_search_area_point_to_original_point(
        [rect["left"], rect["top"]], mapping
    )
    scale = (mapping or {}).get("scale", 1)
    return {
        "left": left,
        "top": top,
        "width": (rect["width"] - 1) / scale + 1,
        "height": (rect["height"] - 1) / scale + 1,
    }


def map_search_area_result_to_original_result(
    result: Dict[str, Any], mapping: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Restore a complete locate result; center and bbox map independently."""
    mapped: Dict[str, Any] = {
        "center": map_search_area_point_to_original_point(result["center"], mapping)
    }
    if result.get("rect"):
        mapped["rect"] = map_search_area_rect_to_original_rect(result["rect"], mapping)
    return mapped


__all__ = [
    "map_search_area_point_to_original_point",
    "map_search_area_rect_to_original_rect",
    "map_search_area_result_to_original_result",
]
