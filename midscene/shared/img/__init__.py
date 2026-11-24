"""Image helpers shared by CLI tool surfaces (upstream shared/src/img)."""

import base64 as _base64
from typing import Any, Optional

from midscene.shared.img.box_select import (
    composite_point_marker,
    composite_rect_marker,
)
from midscene.shared.img.info import (
    encoded_image_info_of_buffer,
    image_info_of_base64,
    is_valid_image_buffer,
    is_valid_jpeg_image_buffer,
    is_valid_png_image_buffer,
    validate_screenshot_buffer,
)
from midscene.shared.img.transform import (
    crop_by_rect,
    image_size,
    padding_to_match_block_by_base64,
    resize_long_edge,
)

_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _normalize_base64_body(value: str) -> str:
    return "".join(value.split())


def detect_image_mime_type_from_buffer(buffer: bytes) -> str | None:
    for magic, mime_type in _IMAGE_MAGIC:
        if buffer.startswith(magic):
            return mime_type
    if buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP":
        return "image/webp"
    return None


def parse_base64(full_base64_string: str) -> dict[str, Any]:
    """Split a data URL (or raw base64 body) into mimeType and body."""
    try:
        separator = ";base64,"
        index = full_base64_string.find(separator)
        if index == -1:
            body = _normalize_base64_body(full_base64_string)
            mime_type = detect_image_mime_type_from_buffer(_base64.b64decode(body))
            if not mime_type:
                raise ValueError("Invalid base64 string")
            return {"mimeType": mime_type, "body": body}
        return {
            # 5 means 'data:'
            "mimeType": full_base64_string[5:index],
            "body": _normalize_base64_body(
                full_base64_string[index + len(separator) :]
            ),
        }
    except Exception as error:  # noqa: BLE001 - mirrors upstream message
        raise ValueError(
            "parseBase64 fail because intput is not a valid base64 string: "
            f"{full_base64_string}"
        ) from error


__all__ = [
    "composite_point_marker",
    "composite_rect_marker",
    "crop_by_rect",
    "detect_image_mime_type_from_buffer",
    "encoded_image_info_of_buffer",
    "image_info_of_base64",
    "image_size",
    "is_valid_image_buffer",
    "is_valid_jpeg_image_buffer",
    "is_valid_png_image_buffer",
    "padding_to_match_block_by_base64",
    "parse_base64",
    "resize_long_edge",
    "validate_screenshot_buffer",
]
