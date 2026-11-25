"""Image encode/decode/crop/resize helpers (upstream shared/src/img/transform.ts).

Upstream delegates to sharp in Node.js and Photon in browsers; the Python SDK
uses Pillow for every backend. The public surface mirrors the upstream module,
including the JPEG/format guarantees and error messages.
"""

from __future__ import annotations

import base64
import io
import math
import os
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx
from PIL.Image import Image as PILImage

from midscene.shared.img.info import encoded_image_info_of_buffer

if TYPE_CHECKING:
    from PIL.Image import Resampling
    from PIL.ImageFile import ImageFile


class _ImageModule(Protocol):
    """Typed facade over Pillow's dynamically imported image module."""

    LANCZOS: Resampling
    NEAREST: Resampling
    open: Callable[..., ImageFile]
    new: Callable[..., PILImage]

    def alpha_composite(self, im1: PILImage, im2: PILImage, /) -> PILImage: ...


def _pil() -> _ImageModule:
    import PIL.Image as image_module

    # Pillow defines resampling constants dynamically during module import.
    return cast(_ImageModule, image_module)


def _js_round(value: float) -> int:
    """``Math.round`` semantics (half rounds up, unlike Python's banker's)."""
    return int(math.floor(value + 0.5))


def _is_positive_integer(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and float(value).is_integer()
        and value > 0
    )


def _clamp_rect(rect: dict[str, float], size: dict[str, int]) -> dict[str, float]:
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


def _detect_image_mime_type_from_buffer(buffer: bytes) -> str | None:
    """Detect the encoded image mime type from its magic bytes."""
    if len(buffer) >= 8 and buffer[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(buffer) >= 3 and buffer[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(buffer) >= 6 and buffer[:3] == b"GIF":
        return "image/gif"
    if len(buffer) >= 12 and buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP":
        return "image/webp"
    if len(buffer) >= 2 and buffer[:2] == b"BM":
        return "image/bmp"
    return None


def _parse_base64(full_base64_string: str) -> dict[str, str]:
    """Split a data URL (or raw base64 body) into ``mimeType`` and ``body``."""
    try:
        separator = ";base64,"
        index = full_base64_string.find(separator)
        if index == -1:
            body = normalize_base64_body(full_base64_string)
            mime_type = _detect_image_mime_type_from_buffer(base64.b64decode(body))
            if mime_type is None:
                raise ValueError("Invalid base64 string")
            return {"mimeType": mime_type, "body": body}
        return {
            # 5 means 'data:'
            "mimeType": full_base64_string[5:index],
            "body": normalize_base64_body(full_base64_string[index + len(separator) :]),
        }
    except Exception as error:  # noqa: BLE001 - mirrors upstream message
        raise ValueError(
            "parseBase64 fail because intput is not a valid base64 string: "
            f"{full_base64_string}"
        ) from error


def _encode_jpeg_bytes(image: PILImage, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, subsampling=0)
    return buffer.getvalue()


def decode_base64_image(image_base64: str) -> PILImage:
    Image = _pil()
    raw = (
        image_base64.split(",", 1)[1]
        if image_base64.startswith("data:")
        else image_base64
    )
    image = Image.open(io.BytesIO(base64.b64decode(raw)))
    return image.convert("RGB")


def encode_base64_image(image: PILImage, quality: int = 90) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(
        _encode_jpeg_bytes(image, quality)
    ).decode("ascii")


def image_size(image_base64: str) -> dict[str, int]:
    """Pixel size of an image payload."""
    width, height = decode_base64_image(image_base64).size
    return {"width": width, "height": height}


def save_base64_image(options: dict[str, str]) -> None:
    """Save a base64-encoded image to ``options['outputPath']``."""
    body = _parse_base64(options["base64Data"])["body"]
    with open(options["outputPath"], "wb") as handle:
        handle.write(base64.b64decode(body))


def _resize_image_buffer(
    input_format: str,
    input_data: bytes | str,
    target_size: dict[str, int],
    *,
    source_size: dict[str, int] | None = None,
    preserve_original_when_unchanged: bool,
    jpeg_quality: int,
) -> dict[str, Any]:
    if isinstance(input_data, str):
        raise ValueError("inputData is base64, use resizeImgBase64 instead")

    target_width = target_size.get("width")
    target_height = target_size.get("height")
    if (
        not target_width
        or not target_height
        or (target_width <= 0 or target_height <= 0)
    ):
        raise AssertionError("newSize must be positive")

    Image = _pil()
    original_width = (source_size or {}).get("width")
    original_height = (source_size or {}).get("height")
    image = Image.open(io.BytesIO(input_data))
    image.load()
    if not original_width or not original_height:
        original_width, original_height = image.size
    if not original_width or not original_height:
        raise ValueError("Undefined width or height from the input image.")

    dimensions_unchanged = (
        target_width == original_width and target_height == original_height
    )
    if preserve_original_when_unchanged and dimensions_unchanged:
        return {"buffer": input_data, "format": input_format}

    resized: PILImage = (
        image
        if dimensions_unchanged
        else image.resize((target_width, target_height), Image.LANCZOS)
    )
    return {
        "buffer": _encode_jpeg_bytes(resized, jpeg_quality),
        # by the JPEG encoder
        "format": "jpeg",
    }


def resize_and_convert_img_buffer(
    input_format: str,
    input_data: bytes,
    new_size: dict[str, int],
) -> dict[str, Any]:
    """Resize an image buffer, preserving bytes/format when size is unchanged."""
    return _resize_image_buffer(
        input_format,
        input_data,
        new_size,
        preserve_original_when_unchanged=True,
        jpeg_quality=90,
    )


def convert_img_buffer_to_jpeg(
    input_data: bytes,
    quality: int = 90,
) -> bytes:
    """Convert an image buffer to JPEG without changing its dimensions."""
    Image = _pil()
    try:
        with Image.open(io.BytesIO(input_data)) as image:
            image.load()
            return _encode_jpeg_bytes(image, quality)
    except Exception as error:  # noqa: BLE001 - mirrors upstream failure
        raise ValueError(
            f"Failed to convert image to JPEG with Pillow: {error}"
        ) from error


def infer_base64_image_format(base64_body: str) -> str:
    if base64_body.startswith("iVBORw0KGgo"):
        return "png"
    return "jpeg"


def create_img_base64_by_format(image_format: str, body: str) -> str:
    return f"data:image/{image_format};base64,{normalize_base64_body(body)}"


def _validate_jpeg_quality(jpeg_quality: Any) -> None:
    if (
        not isinstance(jpeg_quality, (int, float))
        or isinstance(jpeg_quality, bool)
        or not math.isfinite(jpeg_quality)
        or not float(jpeg_quality).is_integer()
        or jpeg_quality < 1
        or jpeg_quality > 100
    ):
        raise ValueError(
            "jpegQuality must be an integer between 1 and 100. "
            f"Received: {jpeg_quality}"
        )


def _validate_image_size(size: dict[str, Any], label: str) -> None:
    width = size.get("width")
    height = size.get("height")
    if not _is_positive_integer(width) or not _is_positive_integer(height):
        raise ValueError(
            f"{label} width and height must be positive integers. "
            f"Received width: {width}, height: {height}"
        )


def normalize_screenshot_base64(
    base64: str, options: dict[str, Any] | None = None
) -> str:
    """Normalize a PNG/JPEG screenshot to a canonical data URL."""
    label = (options or {}).get("label") or "screenshot base64"
    trimmed_base64 = base64.strip()
    if not trimmed_base64:
        raise ValueError(f"{label} cannot be empty")

    match = re.match(
        r"^data:image/(png|jpe?g);base64,([\s\S]*)$",
        trimmed_base64,
        re.IGNORECASE,
    )
    if match:
        image_format = match.group(1).lower()
        if image_format == "jpg":
            image_format = "jpeg"
        body = match.group(2)
        if not normalize_base64_body(body):
            raise ValueError(f"{label} cannot be empty")
        return create_img_base64_by_format(image_format, body)

    if trimmed_base64.startswith("data:"):
        raise ValueError(
            f"{label} must be a PNG/JPEG data URI or raw PNG base64 string"
        )

    if not re.fullmatch(r"[A-Za-z0-9+/=\s]+", trimmed_base64):
        raise ValueError(
            f"{label} must be a PNG/JPEG data URI or raw PNG base64 string"
        )

    return create_img_base64_by_format("png", trimmed_base64)


def normalize_base64_image(base64: str) -> str:
    trimmed_base64 = base64.strip()
    if re.match(
        r"^data:image/[a-zA-Z0-9.+-]+;base64,",
        trimmed_base64,
        re.IGNORECASE,
    ):
        return trimmed_base64

    base64_body = normalize_base64_body(trimmed_base64)
    if not base64_body:
        raise ValueError("base64 image must include image data")
    return create_img_base64_by_format(
        infer_base64_image_format(base64_body),
        base64_body,
    )


def convert_base64_image_to_jpeg(
    input_base64: str,
    jpeg_quality: int = 90,
) -> str:
    """Represent a PNG/JPEG image as JPEG without resizing."""
    _validate_jpeg_quality(jpeg_quality)
    body = _parse_base64(input_base64)["body"]
    image_buffer = base64.b64decode(body)
    detected_mime_type = _detect_image_mime_type_from_buffer(image_buffer)
    if detected_mime_type == "image/jpeg":
        return create_img_base64_by_format("jpeg", body)
    if detected_mime_type != "image/png":
        raise ValueError(
            "inputBase64 must contain a PNG or JPEG image. Detected: "
            f"{detected_mime_type or 'unsupported format'}"
        )

    jpeg_buffer = convert_img_buffer_to_jpeg(image_buffer, jpeg_quality)
    return create_img_base64_by_format(
        "jpeg", base64.b64encode(jpeg_buffer).decode("ascii")
    )


def resize_base64_image_to_jpeg(input_base64: str, options: dict[str, Any]) -> str:
    """Resize a PNG/JPEG image and guarantee JPEG output."""
    jpeg_quality = options.get("jpegQuality")
    if jpeg_quality is None:
        jpeg_quality = 90
    _validate_jpeg_quality(jpeg_quality)
    target_size = options["targetSize"]
    _validate_image_size(target_size, "targetSize")

    parsed = _parse_base64(input_base64)
    body, mime_type = parsed["body"], parsed["mimeType"]
    image_buffer = base64.b64decode(body)
    encoded_source_size = encoded_image_info_of_buffer(image_buffer)
    source_size_option = options.get("sourceSize")
    if source_size_option:
        _validate_image_size(source_size_option, "sourceSize")
        if (
            source_size_option["width"] != encoded_source_size["width"]
            or source_size_option["height"] != encoded_source_size["height"]
        ):
            raise ValueError(
                f"sourceSize {source_size_option['width']}x"
                f"{source_size_option['height']} does not match encoded "
                "image dimensions "
                f"{encoded_source_size['width']}x"
                f"{encoded_source_size['height']}"
            )
    source_size = encoded_source_size
    dimensions_unchanged = (
        source_size["width"] == target_size["width"]
        and source_size["height"] == target_size["height"]
    )
    detected_mime_type = _detect_image_mime_type_from_buffer(image_buffer)
    if dimensions_unchanged and detected_mime_type == "image/jpeg":
        return create_img_base64_by_format("jpeg", body)

    input_format = (
        detected_mime_type.split("/")[1]
        if detected_mime_type
        else mime_type.split("/")[1]
    )
    result = _resize_image_buffer(
        input_format,
        image_buffer,
        target_size,
        source_size=source_size,
        preserve_original_when_unchanged=False,
        jpeg_quality=cast(int, jpeg_quality),
    )
    return create_img_base64_by_format(
        "jpeg", base64.b64encode(result["buffer"]).decode("ascii")
    )


def constrain_base64_image_to_max_size(
    input_base64: str, options: dict[str, Any]
) -> str:
    """Constrain the longest edge while preserving the aspect ratio."""
    max_size = options.get("maxSize")
    if not _is_positive_integer(max_size):
        raise ValueError(f"maxSize must be a positive integer. Received: {max_size}")

    jpeg_quality = options.get("jpegQuality")
    if jpeg_quality is None:
        jpeg_quality = 90
    _validate_jpeg_quality(jpeg_quality)

    parsed = _parse_base64(input_base64)
    body, mime_type = parsed["body"], parsed["mimeType"]
    image_buffer = base64.b64decode(body)
    source_size = encoded_image_info_of_buffer(image_buffer)
    max_size_value = cast(int, max_size)  # Validated as a positive integer above.
    largest_dimension = max(source_size["width"], source_size["height"])
    if largest_dimension <= max_size_value:
        return input_base64

    scale = max_size_value / largest_dimension
    target_size = {
        "width": max(1, _js_round(source_size["width"] * scale)),
        "height": max(1, _js_round(source_size["height"] * scale)),
    }
    detected_mime_type = _detect_image_mime_type_from_buffer(image_buffer)
    input_format = (
        detected_mime_type.split("/")[1]
        if detected_mime_type
        else mime_type.split("/")[1]
    )
    result = _resize_image_buffer(
        input_format,
        image_buffer,
        target_size,
        source_size=source_size,
        preserve_original_when_unchanged=False,
        jpeg_quality=cast(int, jpeg_quality),
    )
    return create_img_base64_by_format(
        "jpeg", base64.b64encode(result["buffer"]).decode("ascii")
    )


def resize_img_base64(input_base64: str, new_size: dict[str, int]) -> str:
    """Historical resize helper: unchanged input keeps its original format."""
    parsed = _parse_base64(input_base64)
    image_buffer = base64.b64decode(parsed["body"])
    result = resize_and_convert_img_buffer(
        parsed["mimeType"].split("/")[1], image_buffer, new_size
    )
    return create_img_base64_by_format(
        result["format"], base64.b64encode(result["buffer"]).decode("ascii")
    )


def zoom_for_gpt4o(original_width: float, original_height: float) -> dict[str, int]:
    """Scale an image into GPT-4o's high-detail 2048x768 budget."""
    max_width = 2048
    max_height = 768
    new_width = original_width
    new_height = original_height

    aspect_ratio = original_width / original_height
    if original_width > max_width:
        new_width = max_width
        new_height = new_width / aspect_ratio
    if new_height > max_height:
        new_height = max_height
        new_width = new_height * aspect_ratio

    return {
        "width": _js_round(new_width),
        "height": _js_round(new_height),
    }


def photon_from_base64(base64_data: str) -> PILImage:
    """Decode an image into an RGBA pixel buffer (Pillow stand-in for Photon)."""
    Image = _pil()
    body = _parse_base64(base64_data)["body"]
    image = Image.open(io.BytesIO(base64.b64decode(body)))
    image.load()
    return image.convert("RGBA")


def photon_to_base64(image: PILImage, quality: int = 90) -> str:
    """Encode an RGBA pixel buffer as a JPEG data URL."""
    return encode_base64_image(image, quality)


def padding_to_match_block(image: PILImage, block_size: int = 28) -> dict[str, Any]:
    """Pad the right/bottom edges with white so both are multiples of a block."""
    Image = _pil()
    width, height = image.size
    target_width = math.ceil(width / block_size) * block_size
    target_height = math.ceil(height / block_size) * block_size

    if target_width == width and target_height == height:
        return {"width": width, "height": height, "image": image}

    mode = image.mode
    background = (255, 255, 255) if mode == "RGB" else (255, 255, 255, 255)
    padded = Image.new(mode, (target_width, target_height), background)
    padded.paste(image, (0, 0))
    return {
        "width": target_width,
        "height": target_height,
        "image": padded,
    }


def padding_to_match_block_by_base64(
    image_base64: str, block_size: int = 28
) -> dict[str, Any]:
    """Pad right/bottom with white so both edges are multiples of ``block_size``."""
    image = photon_from_base64(image_base64)
    width, height = image.size
    target_width = math.ceil(width / block_size) * block_size
    target_height = math.ceil(height / block_size) * block_size
    if target_width == width and target_height == height:
        return {
            "width": width,
            "height": height,
            "imageBase64": image_base64,
        }

    padded = padding_to_match_block(image, block_size)
    return {
        "width": padded["width"],
        "height": padded["height"],
        "imageBase64": photon_to_base64(padded["image"]),
    }


def crop_by_rect(
    image_base64: str, rect: dict[str, float]
) -> tuple[str, dict[str, int]]:
    """Crop ``rect`` out of the screenshot; returns (payload, size)."""
    image = decode_base64_image(image_base64)
    left = math.trunc(rect["left"])
    top = math.trunc(rect["top"])
    width = math.trunc(rect["left"] + rect["width"]) - left
    height = math.trunc(rect["top"] + rect["height"]) - top
    cropped = image.crop((left, top, left + width, top + height))
    return encode_base64_image(cropped), {
        "width": width,
        "height": height,
    }


def resize_long_edge(
    image_base64: str, max_long_edge: int = 1000, max_upscale: float = 2.0
) -> str | None:
    """Upscale a small crop to at most ``max_upscale`` (upstream resize rule)."""
    Image = _pil()
    image = decode_base64_image(image_base64)
    long_edge = max(image.width, image.height)
    if not long_edge:
        return None
    scale = min(max_upscale, max_long_edge / long_edge)
    if scale <= 1.05:
        return None
    target = (
        max(1, _js_round(image.width * scale)),
        max(1, _js_round(image.height * scale)),
    )
    return encode_base64_image(image.resize(target, Image.LANCZOS))


def scale_image(image_base64: str, scale: float) -> dict[str, Any]:
    """Scale an image by ``scale`` and re-encode it as JPEG."""
    if scale <= 0:
        raise ValueError("Scale factor must be positive")

    Image = _pil()
    parsed = _parse_base64(image_base64)
    image = Image.open(io.BytesIO(base64.b64decode(parsed["body"])))
    image.load()
    original_width, original_height = image.size
    if not original_width or not original_height:
        raise ValueError("Failed to get image dimensions")

    new_width = _js_round(original_width * scale)
    new_height = _js_round(original_height * scale)
    resized = image.resize((new_width, new_height), Image.LANCZOS)
    return {
        "width": new_width,
        "height": new_height,
        "imageBase64": encode_base64_image(resized, 90),
    }


def pad_base64_image_to_minimum_size(image_base64: str, minimum: int) -> dict[str, Any]:
    """Pad the right and bottom edges with white to a minimum size."""
    if not _is_positive_integer(minimum):
        raise AssertionError("minimum must be a positive integer")
    Image = _pil()
    body = _parse_base64(image_base64)["body"]
    buffer = base64.b64decode(body)
    size = encoded_image_info_of_buffer(buffer)
    width = max(minimum, size["width"])
    height = max(minimum, size["height"])
    if width == size["width"] and height == size["height"]:
        return {"imageBase64": image_base64, "width": width, "height": height}

    image = Image.open(io.BytesIO(buffer))
    image.load()
    padded = Image.new("RGB", (width, height), (255, 255, 255))
    padded.paste(image.convert("RGB"), (0, 0))
    return {
        "imageBase64": create_img_base64_by_format(
            "jpeg", base64.b64encode(_encode_jpeg_bytes(padded, 90)).decode()
        ),
        "width": width,
        "height": height,
    }


def http_img2_base64(url: str) -> str:
    """Fetch an HTTP image and return it as a data URL."""
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
    if response.status_code < 200 or response.status_code > 299:
        raise ValueError(f"Failed to fetch image: {url}")
    content_type = response.headers.get("content-type")
    if not content_type:
        raise ValueError(f"Failed to fetch image: {url}")
    if not content_type.startswith("image/"):
        raise AssertionError(
            f"The url {url} is not a image, because of content-type in "
            f"header is {content_type}."
        )
    return f"data:{content_type};base64," + base64.b64encode(response.content).decode(
        "ascii"
    )


def local_img2_base64(img_path: str, without_header: bool = False) -> str:
    """Convert a local image file to a base64 string."""
    with open(img_path, "rb") as handle:
        body = base64.b64encode(handle.read()).decode("ascii")
    if without_header:
        return body

    image_type = os.path.splitext(img_path)[1].lstrip(".")
    final_type = "svg+xml" if image_type == "svg" else (image_type or "jpg")
    return f"data:image/{final_type};base64,{body}"


def _js_typeof(value: Any) -> str:
    if value is None:
        return "object"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if callable(value):
        return "function"
    return "object"


def _js_to_string(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list, tuple)):
        if isinstance(value, dict):
            return "[object Object]"
        return ",".join(_js_to_string(item) for item in value)
    return str(value)


def pre_process_image_url(url: Any, convert_http_image_2_base64: bool) -> str:
    """Resolve a data URL, HTTP URL, or local path to a model-ingestable URL."""
    if not isinstance(url, str):
        raise ValueError(
            "url must be a string, but got "
            f"{_js_to_string(url)} with type {_js_typeof(url)}"
        )
    if url.startswith("data:"):
        parsed = _parse_base64(url)
        return f"data:{parsed['mimeType']};base64,{parsed['body']}"
    if url.startswith("http://") or url.startswith("https://"):
        if not convert_http_image_2_base64:
            return url
        return http_img2_base64(url)
    return local_img2_base64(url)


__all__ = [
    "constrain_base64_image_to_max_size",
    "convert_base64_image_to_jpeg",
    "convert_img_buffer_to_jpeg",
    "create_img_base64_by_format",
    "crop_by_rect",
    "decode_base64_image",
    "encode_base64_image",
    "http_img2_base64",
    "image_size",
    "infer_base64_image_format",
    "local_img2_base64",
    "normalize_base64_body",
    "normalize_base64_image",
    "normalize_screenshot_base64",
    "pad_base64_image_to_minimum_size",
    "padding_to_match_block",
    "padding_to_match_block_by_base64",
    "photon_from_base64",
    "photon_to_base64",
    "pre_process_image_url",
    "resize_and_convert_img_buffer",
    "resize_base64_image_to_jpeg",
    "resize_img_base64",
    "resize_long_edge",
    "save_base64_image",
    "scale_image",
    "zoom_for_gpt4o",
]
