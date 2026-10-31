"""DeepLocate search-area helpers.

Synced from upstream packages/core/src/ai-model/workflows/grounding/
(search-area.ts, search-area-mapping.ts).
"""

import base64
import io
from typing import Any, Dict, List, Optional, Sequence

from .context_utils import get_screenshot_base64, get_shot_size

MIN_SEARCH_AREA = 400 * 400
EXPAND_SIZE = 100


def merge_search_area_results(
    target: Dict[str, Any], references: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, float]:
    """Merge target and reference regions into one rect (point results cover
    one pixel)."""
    bounds = []
    for result in [target, *(references or [])]:
        rect = result.get("rect")
        center = result.get("center", (0, 0))
        left = rect["left"] if rect else round(center[0])
        top = rect["top"] if rect else round(center[1])
        width = rect["width"] if rect else 1
        height = rect["height"] if rect else 1
        bounds.append(
            {"left": left, "top": top, "right": left + width, "bottom": top + height}
        )
    left = min(b["left"] for b in bounds)
    top = min(b["top"] for b in bounds)
    right = max(b["right"] for b in bounds)
    bottom = max(b["bottom"] for b in bounds)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def expand_search_area(rect: Dict[str, float], screen_size: Dict[str, Any]) -> Dict[str, float]:
    """Expand the search region toward a minimum area of 160,000 square pixels.

    Step 1: extend 100px on each side (clamped to screen boundaries).
    Step 2: scale proportionally from the center toward the minimum area.
    """
    width = screen_size["width"]
    height = screen_size["height"]

    expanded_left = max(rect["left"] - EXPAND_SIZE, 0)
    expanded_top = max(rect["top"] - EXPAND_SIZE, 0)
    expand_rect = {
        "left": expanded_left,
        "top": expanded_top,
        "width": min(
            rect["left"] - expanded_left + rect["width"] + EXPAND_SIZE,
            width - expanded_left,
        ),
        "height": min(
            rect["top"] - expanded_top + rect["height"] + EXPAND_SIZE,
            height - expanded_top,
        ),
    }

    current_area = expand_rect["width"] * expand_rect["height"]
    if current_area >= MIN_SEARCH_AREA:
        return expand_rect

    center_x = expand_rect["left"] + expand_rect["width"] / 2
    center_y = expand_rect["top"] + expand_rect["height"] / 2
    scale_factor = (MIN_SEARCH_AREA / current_area) ** 0.5
    new_width = round(expand_rect["width"] * scale_factor)
    new_height = round(expand_rect["height"] * scale_factor)
    new_left = round(center_x - new_width / 2)
    new_top = round(center_y - new_height / 2)
    left = max(new_left, 0)
    top = max(new_top, 0)
    return {
        "left": left,
        "top": top,
        "width": min(new_width, width - left),
        "height": min(new_height, height - top),
    }


def _crop_and_scale(
    image_base64: str, rect: Dict[str, float], scale_ratio: float
) -> Any:
    from PIL import Image

    raw = image_base64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    image = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
    left, top = int(rect["left"]), int(rect["top"])
    right = min(int(rect["left"] + rect["width"]), image.width)
    bottom = min(int(rect["top"] + rect["height"]), image.height)
    cropped = image.crop((left, top, right, bottom))

    scaled = cropped.resize(
        (
            max(1, int(cropped.width * scale_ratio)),
            max(1, int(cropped.height * scale_ratio)),
        )
    )
    buffer = io.BytesIO()
    scaled.save(buffer, format="JPEG", quality=95)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return scaled.width, scaled.height, f"data:image/jpeg;base64,{encoded}"


def build_search_area_config(
    context: Any, base_rect: Dict[str, float]
) -> Dict[str, Any]:
    """Crop the section from the screenshot and upscale it for the second pass."""
    scale_ratio = 2
    section_rect = expand_search_area(base_rect, get_shot_size(context))
    screenshot = get_screenshot_base64(context)

    width, height, image_base64 = _crop_and_scale(
        screenshot, section_rect, scale_ratio
    )
    return {
        "source_rect": section_rect,
        "image": {
            "imageBase64": image_base64,
            "width": width,
            "height": height,
        },
        "mapping": {
            "offset": {
                "x": section_rect["left"],
                "y": section_rect["top"],
            },
            "scale": scale_ratio,
        },
    }


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
