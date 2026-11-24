"""Image header inspection and validation.

Synced from upstream packages/shared/src/img/info.ts. Dimensions are read from
the encoded PNG/JPEG header without decoding pixels where possible; full
decoding is delegated to Pillow for the base64 entry point.
"""

import base64
import io
import re
import struct
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND_CHUNK = b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _is_jpeg_start_of_frame_marker(marker: int) -> bool:
    return 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC)


def _jpeg_info_from_buffer(image_buffer: bytes) -> dict[str, int]:
    offset = 2
    length = len(image_buffer)
    while offset < length:
        if image_buffer[offset] != 0xFF:
            offset += 1
            continue

        while offset < length and image_buffer[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break

        marker = image_buffer[offset]
        offset += 1
        if marker in (0xD9, 0xDA):
            break
        if marker == 0x01 or marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > length:
            break

        segment_length = struct.unpack(">H", image_buffer[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > length:
            break
        if _is_jpeg_start_of_frame_marker(marker):
            if segment_length < 7:
                break
            height = struct.unpack(">H", image_buffer[offset + 3 : offset + 5])[0]
            width = struct.unpack(">H", image_buffer[offset + 5 : offset + 7])[0]
            if not width or not height:
                raise ValueError("Invalid image: cannot get width or height")
            return {"width": width, "height": height}
        offset += segment_length

    raise ValueError("Invalid image: cannot get JPEG width or height")


def encoded_image_info_of_buffer(image_buffer: bytes) -> dict[str, int]:
    """Read PNG/JPEG dimensions from the encoded header."""
    if is_valid_png_image_buffer(image_buffer):
        width = struct.unpack(">I", image_buffer[16:20])[0]
        height = struct.unpack(">I", image_buffer[20:24])[0]
        if not width or not height:
            raise ValueError("Invalid image: cannot get width or height")
        return {"width": width, "height": height}
    if is_valid_jpeg_image_buffer(image_buffer):
        return _jpeg_info_from_buffer(image_buffer)
    raise ValueError("Invalid image: unsupported format")


def image_info_of_base64(image_base64: str | bytes | bytearray) -> dict[str, int]:
    """Decode a base64 image (with or without data URL prefix) via Pillow."""
    if isinstance(image_base64, (bytes, bytearray)):
        image_base64 = bytes(image_base64).decode("ascii")
    base64_data = re.sub(r"^data:image/\w+;base64,", "", image_base64)
    base64_data = re.sub(r"\s", "", base64_data)
    if not base64_data:
        raise ValueError("Invalid image: empty base64 data")
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", base64_data) or (
        len(base64_data) % 4 == 1
    ):
        raise ValueError("Invalid image: malformed base64 data")

    image_buffer = base64.b64decode(base64_data)
    if not is_valid_image_buffer(image_buffer):
        raise ValueError("Invalid image: unsupported format")

    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_buffer)) as image:
            width, height = image.size
    except Exception as error:  # noqa: BLE001 - mirrors upstream message
        raise ValueError(
            f"Invalid image: failed to decode base64 data ({error})"
        ) from error
    if not width or not height:
        raise ValueError("Invalid image: cannot get width or height")
    return {"width": width, "height": height}


def is_valid_png_image_buffer(buffer: bytes | None) -> bool:
    """A PNG must carry the signature and end with the IEND chunk."""
    if not buffer or len(buffer) < 20:
        return False
    if not buffer.startswith(PNG_SIGNATURE):
        return False
    return buffer.endswith(PNG_IEND_CHUNK)


def is_valid_jpeg_image_buffer(buffer: bytes | None) -> bool:
    if not buffer or len(buffer) < 3:
        return False
    return buffer[0] == 0xFF and buffer[1] == 0xD8 and buffer[2] == 0xFF


def is_valid_image_buffer(buffer: bytes | None) -> bool:
    return is_valid_png_image_buffer(buffer) or is_valid_jpeg_image_buffer(buffer)


def validate_screenshot_buffer(
    screenshot_buffer: bytes | None,
    *,
    label: str,
    min_buffer_size: int = 0,
) -> None:
    buffer_size = len(screenshot_buffer) if screenshot_buffer else 0
    if not screenshot_buffer or buffer_size == 0:
        raise ValueError(f"{label} validation failed: buffer size {buffer_size} bytes")
    if not is_valid_image_buffer(screenshot_buffer):
        raise ValueError(f"{label} buffer has invalid image format")
    if min_buffer_size > 0 and buffer_size < min_buffer_size:
        raise ValueError(
            f"{label} validation failed: buffer size {buffer_size} bytes "
            f"(minimum: {min_buffer_size})"
        )


__all__: Any = [
    "encoded_image_info_of_buffer",
    "image_info_of_base64",
    "is_valid_image_buffer",
    "is_valid_jpeg_image_buffer",
    "is_valid_png_image_buffer",
    "validate_screenshot_buffer",
]
