"""Screenshot annotation helpers (upstream shared/src/img/box-select.ts).

Draws the temporary target markers the describer prompt refers to: a ring with
a crosshair for a point, and a border with a center cross for a rect. Everything
returns a model-ingestable ``data:image/jpeg;base64,...`` URL, like upstream.
"""

from __future__ import annotations

from typing import Dict

from midscene.shared.img.transform import (
    decode_base64_image,
    encode_base64_image,
)

POINT_MARKER_RADIUS = 14
MARKER_THICKNESS = 3
MARKER_COLOR = (0xC6, 0x23, 0x00, 0xEE)
MARKER_BORDER = (0xFF, 0xFF, 0xFF, 0xFF)


def _pil():
    from PIL import Image, ImageDraw

    return Image, ImageDraw


def composite_point_marker(
    image_base64: str,
    point: Dict[str, float],
    radius: int = POINT_MARKER_RADIUS,
) -> str:
    """Ring + crosshair at ``point`` (upstream compositePointMarkerImg)."""
    Image, ImageDraw = _pil()
    image = decode_base64_image(image_base64)
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
    return encode_base64_image(
        Image.alpha_composite(image.convert("RGBA"), overlay)
    )


def composite_rect_marker(
    image_base64: str,
    rect: Dict[str, float],
    border_thickness: int = 0,
) -> str:
    """Bordered rect with a center cross (upstream compositeElementInfoImg)."""
    Image, ImageDraw = _pil()
    image = decode_base64_image(image_base64)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top = float(rect["left"]), float(rect["top"])
    right, bottom = left + float(rect["width"]), top + float(rect["height"])
    thickness = border_thickness or (
        1 if (right - left) <= 40 and (bottom - top) <= 40 else 2
    )
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    draw.rectangle(
        [left, top, right, bottom], outline=MARKER_COLOR, width=thickness
    )
    arm = min(6, max(3, (bottom - top) / 4))
    draw.line(
        [(center_x - arm, center_y), (center_x + arm, center_y)],
        fill=MARKER_COLOR,
        width=2,
    )
    draw.line(
        [(center_x, center_y - arm), (center_x, center_y + arm)],
        fill=MARKER_COLOR,
        width=2,
    )
    return encode_base64_image(
        Image.alpha_composite(image.convert("RGBA"), overlay)
    )


__all__ = ["composite_point_marker", "composite_rect_marker"]
