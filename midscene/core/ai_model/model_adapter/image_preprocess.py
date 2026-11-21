"""Screenshot annotation helpers (upstream packages/shared/src/img/box-select.ts).

Draws the temporary target markers the describer prompt refers to: a ring with
a crosshair for a point, and a border with a center cross for a rect. Everything
returns a model-ingestable ``data:image/jpeg;base64,...`` URL, like upstream.

Pillow is imported lazily so importing the package never pulls in its
image stack.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Dict, Optional, Tuple

from midscene.core.service.utils import clamp_rect

POINT_MARKER_RADIUS = 14
MARKER_THICKNESS = 3
MARKER_COLOR = (0xC6, 0x23, 0x00, 0xEE)
MARKER_BORDER = (0xFF, 0xFF, 0xFF, 0xFF)


def _pil():
    from PIL import Image, ImageDraw

    return Image, ImageDraw


def _decode(image_base64: str):
    Image, _ = _pil()
    raw = image_base64.split(",", 1)[1] if image_base64.startswith("data:") else image_base64
    image = Image.open(io.BytesIO(base64.b64decode(raw)))
    return image.convert("RGB")


def _encode(image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90, subsampling=0)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def image_size(image_base64: str) -> Dict[str, int]:
    """Pixel size of an image payload."""
    width, height = _decode(image_base64).size
    return {"width": width, "height": height}



def composite_point_marker(
    image_base64: str,
    point: Dict[str, float],
    radius: int = POINT_MARKER_RADIUS,
) -> str:
    """Ring + crosshair at ``point`` (upstream compositePointMarkerImg)."""
    Image, ImageDraw = _pil()
    image = _decode(image_base64)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x, y = float(point["x"]), float(point["y"])
    ring = max(round(radius), 10)
    draw.ellipse(
        [x - ring - 2, y - ring - 2, x + ring + 2, y + ring + 2],
        outline=MARKER_BORDER,
        width=MARKER_THICKNESS,
    )
    draw.ellipse(
        [x - ring, y - ring, x + ring, y + ring],
        outline=MARKER_COLOR,
        width=MARKER_THICKNESS,
    )
    tick_inner, tick_outer = ring + 5, ring + 12
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        draw.line(
            [
                (x + dx * tick_inner, y + dy * tick_inner),
                (x + dx * tick_outer, y + dy * tick_outer),
            ],
            fill=MARKER_BORDER,
            width=MARKER_THICKNESS,
        )
    return _encode(Image.alpha_composite(image.convert("RGBA"), overlay))


def composite_rect_marker(image_base64: str, rect: Dict[str, float]) -> str:
    """Bordered rect with a center cross (upstream compositeElementInfoImg)."""
    Image, ImageDraw = _pil()
    image = _decode(image_base64)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top = float(rect["left"]), float(rect["top"])
    right, bottom = left + float(rect["width"]), top + float(rect["height"])
    thickness = 1 if (right - left) <= 40 and (bottom - top) <= 40 else 2
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    draw.rectangle([left, top, right, bottom], outline=MARKER_COLOR, width=thickness)
    arm = min(6, max(3, (bottom - top) / 4))
    draw.line([(center_x - arm, center_y), (center_x + arm, center_y)], fill=MARKER_COLOR, width=2)
    draw.line([(center_x, center_y - arm), (center_x, center_y + arm)], fill=MARKER_COLOR, width=2)
    return _encode(Image.alpha_composite(image.convert("RGBA"), overlay))


def crop_image(
    image_base64: str, rect: Dict[str, float]
) -> Tuple[str, Dict[str, int]]:
    """Crop ``rect`` out of the screenshot; returns (payload, size)."""
    image = _decode(image_base64)
    clamped = clamp_rect(rect, {"width": image.width, "height": image.height})
    left, top = int(math.floor(clamped["left"])), int(math.floor(clamped["top"]))
    right = int(math.ceil(left + clamped["width"]))
    bottom = int(math.ceil(top + clamped["height"]))
    cropped = image.crop((left, top, right, bottom))
    return _encode(cropped), {"width": cropped.width, "height": cropped.height}


def resize_long_edge(
    image_base64: str, max_long_edge: int = 1000, max_upscale: float = 2.0
) -> Optional[str]:
    """Upscale a small crop to at most ``max_upscale`` (upstream resize rule)."""
    Image, _ = _pil()
    image = _decode(image_base64)
    long_edge = max(image.width, image.height)
    if not long_edge:
        return None
    scale = min(max_upscale, max_long_edge / long_edge)
    if scale <= 1.05:
        return None
    target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return _encode(image.resize(target, Image.LANCZOS))


__all__ = [
    "clamp_rect",
    "composite_point_marker",
    "composite_rect_marker",
    "crop_image",
    "image_size",
    "resize_long_edge",
]