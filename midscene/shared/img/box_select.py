"""Screenshot annotation helpers (upstream shared/src/img/box-select.ts).

Draws the temporary target markers the describer prompt refers to: a ring with
a crosshair for a point, and a bordered rect (optionally numbered) for elements.
The pixel loops mirror upstream so marker geometry and colors stay identical;
every function returns a model-ingestable ``data:image/jpeg;base64,...`` URL.

Pillow replaces sharp/Photon here but the Pillow JPEG encoder is configured for
4:4:4 chroma like upstream's ``chromaSubsampling: '4:4:4'``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

from midscene.shared.img.transform import (
    _ImageModule,
    decode_base64_image,
    encode_base64_image,
)
from midscene.shared.types import NodeType

if TYPE_CHECKING:
    from PIL import ImageDraw
    from PIL._imaging import PixelAccess
    from PIL.Image import Image as PILImage
    from PIL.PyAccess import PyAccess

    type PixelBuffer = PixelAccess | PyAccess


class _ImageDrawModule(Protocol):
    Draw: Callable[[PILImage], ImageDraw.ImageDraw]


# Simple 5x7 bitmap font for digits 0-9
DIGIT_FONT: dict[str, list[list[int]]] = {
    "0": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
    "1": [
        [0, 0, 1, 0, 0],
        [0, 1, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 1, 1, 1, 0],
    ],
    "2": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [0, 0, 0, 0, 1],
        [0, 0, 1, 1, 0],
        [0, 1, 0, 0, 0],
        [1, 0, 0, 0, 0],
        [1, 1, 1, 1, 1],
    ],
    "3": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [0, 0, 0, 0, 1],
        [0, 0, 1, 1, 0],
        [0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
    "4": [
        [0, 0, 0, 1, 0],
        [0, 0, 1, 1, 0],
        [0, 1, 0, 1, 0],
        [1, 0, 0, 1, 0],
        [1, 1, 1, 1, 1],
        [0, 0, 0, 1, 0],
        [0, 0, 0, 1, 0],
    ],
    "5": [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0],
        [1, 1, 1, 1, 0],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
    "6": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 0],
        [1, 0, 0, 0, 0],
        [1, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
    "7": [
        [1, 1, 1, 1, 1],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 1, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 1, 0, 0],
    ],
    "8": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
    "9": [
        [0, 1, 1, 1, 0],
        [1, 0, 0, 0, 1],
        [1, 0, 0, 0, 1],
        [0, 1, 1, 1, 1],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 0, 1],
        [0, 1, 1, 1, 0],
    ],
}

FONT_WIDTH = 5
FONT_HEIGHT = 7
FONT_SCALE = 2  # Scale up for better visibility

POINT_MARKER_RADIUS = 14
MARKER_THICKNESS = 3
MARKER_COLOR = (0xC6, 0x23, 0x00, 0xEE)
MARKER_BORDER = (0xFF, 0xFF, 0xFF, 0xFF)

Rect = dict[str, float]

# Rect/text colors cycle per element (upstream ``createSvgOverlay``).
_PALETTE = [
    {"rect": (0xC6, 0x23, 0x00, 0xFF), "text": (0xFF, 0xFF, 0xFF, 0xFF)},
    {"rect": (0x00, 0x00, 0xFF, 0xFF), "text": (0xFF, 0xFF, 0xFF, 0xFF)},
    {"rect": (0x8B, 0x45, 0x13, 0xFF), "text": (0xFF, 0xFF, 0xFF, 0xFF)},
    {"rect": (0x3E, 0x7B, 0x27, 0xFF), "text": (0xFF, 0xFF, 0xFF, 0xFF)},
    {"rect": (0x50, 0x00, 0x73, 0xFF), "text": (0xFF, 0xFF, 0xFF, 0xFF)},
]

_POINT_MARKER_COLORS = [
    (0xC6, 0x23, 0x00, 0xEE),
    (0x00, 0x00, 0xFF, 0xEE),
]


def _pil() -> tuple[_ImageModule, _ImageDrawModule]:
    import PIL.Image as image_module
    import PIL.ImageDraw as image_draw_module

    return cast(_ImageModule, image_module), cast(_ImageDrawModule, image_draw_module)


def _js_round(value: float) -> int:
    """``Math.round`` semantics (half rounds up, unlike Python's banker's)."""
    return int(math.floor(value + 0.5))


def _element_value(element: Any, key: str, default: Any = None) -> Any:
    if isinstance(element, dict):
        return element.get(key, default)
    return getattr(element, key, default)


def _draw_digit(
    pixels: PixelBuffer,
    width: int,
    height: int,
    digit: str,
    start_x: int,
    start_y: int,
    color: tuple[int, ...],
) -> None:
    bitmap = DIGIT_FONT.get(digit)
    if not bitmap:
        return

    for row in range(FONT_HEIGHT):
        for col in range(FONT_WIDTH):
            if bitmap[row][col] != 1:
                continue
            for sy in range(FONT_SCALE):
                for sx in range(FONT_SCALE):
                    x = start_x + col * FONT_SCALE + sx
                    y = start_y + row * FONT_SCALE + sy
                    if 0 <= x < width and 0 <= y < height:
                        pixels[x, y] = color


def _draw_number(
    pixels: PixelBuffer,
    width: int,
    height: int,
    num: int,
    start_x: int,
    start_y: int,
    color: tuple[int, ...],
) -> None:
    x = start_x
    for digit in str(num):
        _draw_digit(pixels, width, height, digit, x, start_y, color)
        x += FONT_WIDTH * FONT_SCALE + 1  # 1px spacing between digits


def _get_number_width(num: int) -> int:
    return len(str(num)) * (FONT_WIDTH * FONT_SCALE + 1) - 1


def _draw_rect(
    pixels: PixelBuffer,
    width: int,
    height: int,
    rect: dict[str, float],
    color: tuple[int, ...],
    thickness: int,
) -> None:
    x = math.floor(rect["x"])
    y = math.floor(rect["y"])
    w = math.floor(rect["w"])
    h = math.floor(rect["h"])

    for py in range(y, min(y + h, height)):
        for px in range(x, min(x + w, width)):
            if px < 0 or py < 0:
                continue
            is_left_border = x <= px < x + thickness
            is_right_border = px <= x + w - 1 and px > x + w - thickness - 1
            is_top_border = y <= py < y + thickness
            is_bottom_border = py <= y + h - 1 and py > y + h - thickness - 1
            if is_left_border or is_right_border or is_top_border or is_bottom_border:
                pixels[px, py] = color


def _fill_rect(
    pixels: PixelBuffer,
    width: int,
    height: int,
    rect: dict[str, float],
    color: tuple[int, ...],
) -> None:
    x = math.floor(rect["x"])
    y = math.floor(rect["y"])
    w = math.floor(rect["w"])
    h = math.floor(rect["h"])

    for py in range(y, min(y + h, height)):
        for px in range(x, min(x + w, width)):
            if px < 0 or py < 0:
                continue
            pixels[px, py] = color


def _draw_circle(
    pixels: PixelBuffer,
    width: int,
    height: int,
    center: dict[str, float],
    radius: float,
    color: tuple[int, ...],
    thickness: int = 2,
    fill: bool = False,
) -> None:
    cx = _js_round(center["x"])
    cy = _js_round(center["y"])
    outer_radius = max(_js_round(radius), 1)
    thickness = max(_js_round(thickness), 1)
    inner_radius = max(outer_radius - thickness, 0)
    outer_sq = outer_radius * outer_radius
    inner_sq = inner_radius * inner_radius

    for py in range(cy - outer_radius, cy + outer_radius + 1):
        for px in range(cx - outer_radius, cx + outer_radius + 1):
            if px < 0 or py < 0 or px >= width or py >= height:
                continue
            distance_sq = (px - cx) ** 2 + (py - cy) ** 2
            should_draw = (
                distance_sq <= outer_sq if fill else inner_sq <= distance_sq <= outer_sq
            )
            if should_draw:
                pixels[px, py] = color


def _draw_line(
    pixels: PixelBuffer,
    width: int,
    height: int,
    start: dict[str, float],
    end: dict[str, float],
    color: tuple[int, ...],
    thickness: int = 2,
) -> None:
    x0 = _js_round(start["x"])
    y0 = _js_round(start["y"])
    x1 = _js_round(end["x"])
    y1 = _js_round(end["y"])
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    half_thickness = max(math.floor(thickness / 2), 0)

    for step in range(steps + 1):
        x = _js_round(x0 + ((x1 - x0) * step) / steps)
        y = _js_round(y0 + ((y1 - y0) * step) / steps)
        for dy in range(-half_thickness, half_thickness + 1):
            for dx in range(-half_thickness, half_thickness + 1):
                px = x + dx
                py = y + dy
                if px < 0 or py < 0 or px >= width or py >= height:
                    continue
                pixels[px, py] = color


def _draw_point_marker(
    pixels: PixelBuffer,
    width: int,
    height: int,
    point: dict[str, float],
    radius: float,
    index_id: int = 1,
) -> None:
    marker = _POINT_MARKER_COLORS[(index_id - 1) % len(_POINT_MARKER_COLORS)]
    ring_radius = max(_js_round(radius), 10)

    # Hollow target reticle centered on the point instead of an offset numbered
    # callout bubble, so it is not mistaken for page UI.
    _draw_circle(
        pixels,
        width,
        height,
        point,
        ring_radius + 2,
        MARKER_BORDER,
        thickness=3,
    )
    _draw_circle(
        pixels,
        width,
        height,
        point,
        ring_radius,
        marker,
        thickness=3,
    )

    tick_inner = ring_radius + 5
    tick_outer = ring_radius + 12
    for direction in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        _draw_line(
            pixels,
            width,
            height,
            {
                "x": point["x"] + direction[0] * tick_inner,
                "y": point["y"] + direction[1] * tick_inner,
            },
            {
                "x": point["x"] + direction[0] * tick_outer,
                "y": point["y"] + direction[1] * tick_outer,
            },
            MARKER_BORDER,
            3,
        )


def _create_svg_overlay(
    elements: Sequence[Any],
    image_width: int,
    image_height: int,
    box_padding: int | None = None,
    border_thickness: int | None = None,
    prompt: str | None = None,
    center_point: bool | None = None,
) -> PILImage:
    Image, _ = _pil()
    box_padding = 5 if box_padding is None else box_padding
    border_thickness = 2 if border_thickness is None else border_thickness
    center_point = False if center_point is None else center_point

    overlay = Image.new("RGBA", (image_width, image_height), (0, 0, 0, 0))
    pixels = overlay.load()
    assert pixels is not None

    if prompt:
        prompt_margin = 20
        prompt_height = 30
        prompt_y = image_height - prompt_height - prompt_margin
        _fill_rect(
            pixels,
            image_width,
            image_height,
            {
                "x": 0,
                "y": prompt_y,
                "w": image_width,
                "h": prompt_height,
            },
            (0x00, 0x00, 0x00, 0xCC),
        )
        # The bitmap font only covers digits, so prompt text is not rendered.

    for index, element in enumerate(elements):
        color = _PALETTE[index % len(_PALETTE)]
        element_rect = _element_value(element, "rect") or {}
        rect_left = float(element_rect.get("left", 0))
        rect_top = float(element_rect.get("top", 0))
        rect_width = float(element_rect.get("width", 0))
        rect_height = float(element_rect.get("height", 0))

        padded_left = max(0.0, rect_left - box_padding)
        padded_top = max(0.0, rect_top - box_padding)
        padded_width = min(
            image_width - padded_left,
            rect_width + box_padding * 2,
        )
        padded_height = min(
            image_height - padded_top,
            rect_height + box_padding * 2,
        )
        padded_rect = {
            "x": padded_left,
            "y": padded_top,
            "w": padded_width,
            "h": padded_height,
        }

        _draw_rect(
            pixels,
            image_width,
            image_height,
            padded_rect,
            color["rect"],
            border_thickness,
        )

        if center_point:
            _draw_circle(
                pixels,
                image_width,
                image_height,
                {
                    "x": rect_left + rect_width / 2,
                    "y": rect_top + rect_height / 2,
                },
                4,
                color["rect"],
                fill=True,
            )

        index_id = _element_value(element, "indexId")
        if not isinstance(index_id, (int, float)) or isinstance(index_id, bool):
            continue
        index_id = int(index_id)

        text_width = _get_number_width(index_id)
        text_height = FONT_HEIGHT * FONT_SCALE
        label_width = text_width + 5
        label_height = text_height + 4
        rect_x = padded_left - label_width
        rect_y = (
            padded_top + math.floor(padded_height / 2) - math.floor(text_height / 2) - 2
        )

        def check_overlap(
            x: float,
            y: float,
            _index: int = index,
            _label_width: int = label_width,
            _label_height: int = label_height,
        ) -> bool:
            for other in elements[:_index]:
                other_rect = _element_value(other, "rect") or {}
                other_left = float(other_rect.get("left", 0))
                other_top = float(other_rect.get("top", 0))
                other_width = float(other_rect.get("width", 0))
                other_height = float(other_rect.get("height", 0))
                if (
                    x < other_left + other_width
                    and x + _label_width > other_left
                    and y < other_top + other_height
                    and y + _label_height > other_top
                ):
                    return True
            return False

        def is_within_bounds(
            x: float,
            y: float,
            _label_width: int = label_width,
            _label_height: int = label_height,
        ) -> bool:
            return (
                x >= 0
                and x + _label_width <= image_width
                and y >= 0
                and y + _label_height <= image_height
            )

        if check_overlap(rect_x, rect_y) or not is_within_bounds(rect_x, rect_y):
            top_y = padded_top - label_height - 2
            bottom_y = padded_top + padded_height + 2
            right_x = padded_left + padded_width + 2
            if not check_overlap(padded_left, top_y) and is_within_bounds(
                padded_left, top_y
            ):
                rect_x = padded_left
                rect_y = top_y
            elif not check_overlap(padded_left, bottom_y) and is_within_bounds(
                padded_left, bottom_y
            ):
                rect_x = padded_left
                rect_y = bottom_y
            elif not check_overlap(right_x, padded_top) and is_within_bounds(
                right_x, padded_top
            ):
                rect_x = right_x
                rect_y = padded_top
            else:
                rect_x = padded_left
                rect_y = padded_top + 2

        _fill_rect(
            pixels,
            image_width,
            image_height,
            {
                "x": rect_x,
                "y": rect_y,
                "w": label_width,
                "h": label_height,
            },
            color["rect"],
        )

        # floor() is already integral; the surrounding offset may be fractional.
        text_x = cast(int, rect_x + math.floor((label_width - text_width) / 2))
        text_y = cast(int, rect_y + math.floor((label_height - text_height) / 2))
        _draw_number(
            pixels,
            image_width,
            image_height,
            index_id,
            text_x,
            text_y,
            color["text"],
        )

    return overlay


def _decode_base_image(
    input_img_base64: str,
    size: dict[str, int] | None = None,
) -> PILImage:
    Image, _ = _pil()
    image = decode_base64_image(input_img_base64).convert("RGBA")
    if size:
        width = size.get("width")
        height = size.get("height")
        if width and height and image.size != (width, height):
            image = image.resize((width, height), Image.NEAREST)
    return image


def composite_element_info_img(options: dict[str, Any]) -> str:
    """Draw bordered (and optionally numbered) element rects on a screenshot."""
    Image, _ = _pil()
    input_img_base64 = options.get("inputImgBase64")
    if not input_img_base64:
        raise AssertionError("inputImgBase64 is required")

    image = _decode_base_image(input_img_base64, options.get("size"))
    overlay = _create_svg_overlay(
        options.get("elementsPositionInfo") or [],
        image.width,
        image.height,
        options.get("annotationPadding"),
        options.get("borderThickness"),
        options.get("prompt"),
        options.get("centerPoint"),
    )
    return encode_base64_image(Image.alpha_composite(image, overlay))


def composite_point_marker_img(options: dict[str, Any]) -> str:
    """Draw a centered reticle marker on a screenshot."""
    Image, _ = _pil()
    input_img_base64 = options.get("inputImgBase64")
    if not input_img_base64:
        raise AssertionError("inputImgBase64 is required")

    image = _decode_base_image(input_img_base64, options.get("size"))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pixels = overlay.load()
    assert pixels is not None
    radius = options.get("radius")
    index_id = options.get("indexId")
    _draw_point_marker(
        pixels,
        image.width,
        image.height,
        options["point"],
        POINT_MARKER_RADIUS if radius is None else radius,
        1 if index_id is None else index_id,
    )
    return encode_base64_image(Image.alpha_composite(image, overlay))


def process_image_element_info(options: dict[str, Any]) -> dict[str, str]:
    """Compose the with-text and without-text element images in one call."""
    base64_image = options["inputImgBase64"].split(";base64,")[-1]
    if not base64_image:
        raise AssertionError("base64Image is undefined")

    return {
        "compositeElementInfoImgBase64": composite_element_info_img(
            {
                "inputImgBase64": options["inputImgBase64"],
                "elementsPositionInfo": options["elementsPositionInfo"],
            }
        ),
        "compositeElementInfoImgWithoutTextBase64": (
            composite_element_info_img(
                {
                    "inputImgBase64": options["inputImgBase64"],
                    "elementsPositionInfo": options["elementsPositionInfoWithoutText"],
                }
            )
        ),
    }


def annotate_rects(
    img_base64: str,
    rects: Sequence[Rect],
    prompt: str | None = None,
) -> str:
    """Annotate plain rects with numbered colored borders."""
    elements = [
        {
            "id": f"rect-{index}",
            "rect": rect,
            "indexId": index + 1,
            "attributes": {"nodeType": NodeType.CONTAINER.value},
            "content": "",
            "center": [
                rect["left"] + rect["width"] / 2,
                rect["top"] + rect["height"] / 2,
            ],
        }
        for index, rect in enumerate(rects)
    ]
    return composite_element_info_img(
        {
            "inputImgBase64": img_base64,
            "elementsPositionInfo": elements,
            "annotationPadding": 0,
            "prompt": prompt,
        }
    )


def composite_point_marker(
    image_base64: str,
    point: dict[str, float],
    radius: int = POINT_MARKER_RADIUS,
) -> str:
    """Ring + crosshair at ``point`` (upstream compositePointMarkerImg)."""
    return composite_point_marker_img(
        {
            "inputImgBase64": image_base64,
            "point": point,
            "radius": radius,
        }
    )


def composite_rect_marker(
    image_base64: str,
    rect: dict[str, float],
    border_thickness: int = 0,
) -> str:
    """Bordered rect with a center cross (describe-marker variant)."""
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
    draw.rectangle([left, top, right, bottom], outline=MARKER_COLOR, width=thickness)
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
    return encode_base64_image(Image.alpha_composite(image.convert("RGBA"), overlay))


__all__ = [
    "annotate_rects",
    "composite_element_info_img",
    "composite_point_marker",
    "composite_point_marker_img",
    "composite_rect_marker",
    "process_image_element_info",
]
