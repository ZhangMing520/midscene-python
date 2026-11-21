"""Image encode/decode/crop/resize helpers (upstream shared/src/img/transform.ts).

Upstream delegates to sharp/photon; the Python SDK uses Pillow. Only the
operations used by the SDK are ported.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any, Dict, Optional, Tuple


def _pil():
    from PIL import Image, ImageDraw

    return Image, ImageDraw


def _clamp_rect(
    rect: Dict[str, float], size: Dict[str, int]
) -> Dict[str, float]:
    width = min(float(rect["width"]), float(size["width"]))
    height = min(float(rect["height"]), float(size["height"]))
    return {
        "left": max(0.0, min(float(rect["left"]), float(size["width"]) - width)),
        "top": max(0.0, min(float(rect["top"]), float(size["height"]) - height)),
        "width": width,
        "height": height,
    }


def normalize_base64_body(body: str) -> str:
    return "".join(body.split())


def decode_base64_image(image_base64: str):
    Image, _ = _pil()
    raw = (
        image_base64.split(",", 1)[1]
        if image_base64.startswith("data:")
        else image_base64
    )
    image = Image.open(io.BytesIO(base64.b64decode(raw)))
    return image.convert("RGB")


def encode_base64_image(image, quality: int = 90) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer, format="JPEG", quality=quality, subsampling=0
    )
    return "data:image/jpeg;base64," + base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")


def image_size(image_base64: str) -> Dict[str, int]:
    """Pixel size of an image payload."""
    width, height = decode_base64_image(image_base64).size
    return {"width": width, "height": height}


def crop_by_rect(
    image_base64: str, rect: Dict[str, float]
) -> Tuple[str, Dict[str, int]]:
    """Crop ``rect`` out of the screenshot; returns (payload, size)."""
    image = decode_base64_image(image_base64)
    clamped = _clamp_rect(rect, {"width": image.width, "height": image.height})
    left, top = int(math.floor(clamped["left"])), int(math.floor(clamped["top"]))
    right = int(math.ceil(left + clamped["width"]))
    bottom = int(math.ceil(top + clamped["height"]))
    cropped = image.crop((left, top, right, bottom))
    return encode_base64_image(cropped), {
        "width": cropped.width,
        "height": cropped.height,
    }


def resize_long_edge(
    image_base64: str, max_long_edge: int = 1000, max_upscale: float = 2.0
) -> Optional[str]:
    """Upscale a small crop to at most ``max_upscale`` (upstream resize rule)."""
    Image, _ = _pil()
    image = decode_base64_image(image_base64)
    long_edge = max(image.width, image.height)
    if not long_edge:
        return None
    scale = min(max_upscale, max_long_edge / long_edge)
    if scale <= 1.05:
        return None
    target = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    return encode_base64_image(image.resize(target, Image.LANCZOS))


def padding_to_match_block_by_base64(
    image_base64: str, block_size: int = 28
) -> Dict[str, Any]:
    """Pad right/bottom with white so both edges are multiples of ``block_size``."""
    width, height = (
        image_size(image_base64)["width"],
        image_size(image_base64)["height"],
    )
    target_width = math.ceil(width / block_size) * block_size
    target_height = math.ceil(height / block_size) * block_size
    if target_width == width and target_height == height:
        return {
            "width": width,
            "height": height,
            "imageBase64": image_base64,
        }

    Image, _ = _pil()
    image = decode_base64_image(image_base64)
    padded = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    padded.paste(image, (0, 0))
    return {
        "width": target_width,
        "height": target_height,
        "imageBase64": encode_base64_image(padded),
    }


__all__ = [
    "crop_by_rect",
    "decode_base64_image",
    "encode_base64_image",
    "image_size",
    "normalize_base64_body",
    "padding_to_match_block_by_base64",
    "resize_long_edge",
]
