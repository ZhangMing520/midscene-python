"""Serialized report image references (upstream dump/image-reference.ts).

The Python SDK stores images either inline (data URI / base64 strings in the
dump) or as files next to the report. These helpers decide which strings are
image payloads when a dump is externalized.
"""

import re
from typing import Any, cast
from urllib.parse import quote

_DATA_URI_PATTERN = re.compile(
    r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.*)$", re.IGNORECASE | re.DOTALL
)

_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")

_IMAGE_KEYS = {
    "base64",
    "imagebase64",
    "screenshot",
    "screenshots",
    "screenshot_base64",
}

_IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$", re.IGNORECASE)

KNOWN_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/avif": "avif",
    "image/bmp": "bmp",
}

KNOWN_IMAGE_MIME_TYPES_BY_EXTENSION = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "avif": "image/avif",
    "bmp": "image/bmp",
}


def _has_valid_storage(record: dict[str, Any]) -> bool:
    if record.get("storage") not in ("inline", "file"):
        return False
    return record.get("storage") != "file" or isinstance(record.get("path"), str)


def _has_valid_image_id(record: dict[str, Any]) -> bool:
    value = record.get("id")
    return isinstance(value, str) and bool(_IMAGE_ID_PATTERN.match(value))


def normalize_image_url_ref(value: Any) -> dict[str, Any] | None:
    """Validate a serialized multimodal prompt image reference."""
    if not isinstance(value, dict):
        return None
    mime_type = value.get("mimeType")
    if (
        value.get("type") == "midscene_image_url_ref"
        and _has_valid_image_id(value)
        and isinstance(mime_type, str)
        and mime_type.startswith("image/")
        and _has_valid_storage(value)
    ):
        return value
    return None


def normalize_stored_image_ref(value: Any) -> dict[str, Any] | None:
    # Imported lazily to keep the module free of a screenshot-store cycle.
    from midscene.core.dump.screenshot_store import normalize_screenshot_ref

    return normalize_screenshot_ref(value) or normalize_image_url_ref(value)


def image_file_extension_for_mime_type(mime_type: str) -> str:
    known = KNOWN_IMAGE_EXTENSIONS.get(mime_type.lower())
    if known:
        return known
    subtype = mime_type[len("image/") :].split("+", 1)[0]
    sanitized = re.sub(r"[^a-z0-9]+", "-", subtype.lower()).strip("-")[:32]
    if not sanitized:
        raise ValueError(
            f'Cannot derive a report image file extension for MIME type "{mime_type}"'
        )
    return sanitized


def image_mime_type_for_file_extension(extension: str) -> str | None:
    return KNOWN_IMAGE_MIME_TYPES_BY_EXTENSION.get(extension.lower())


def image_ref_file_extension(ref: dict[str, Any]) -> str:
    return image_file_extension_for_mime_type(ref["mimeType"])


def report_image_asset_path(ref: dict[str, Any]) -> str:
    """Resolve the report-relative asset path for an image reference."""
    if ref.get("storage") == "file" and ref.get("path"):
        return cast(str, ref["path"])
    return f"./screenshots/{quote(str(ref['id']), safe='')}.{image_ref_file_extension(ref)}"


def normalize_screenshot_ref(value: Any) -> dict[str, Any] | None:
    """Re-export of ``screenshot_store.normalize_screenshot_ref``."""
    from midscene.core.dump.screenshot_store import (
        normalize_screenshot_ref as _normalize_screenshot_ref,
    )

    return _normalize_screenshot_ref(value)


def _is_image_string(value: str, key: str | None) -> bool:
    if value.startswith("data:image/"):
        return True
    if not key or key.lower() not in _IMAGE_KEYS:
        return False
    return bool(_BASE64_PATTERN.match(value))


__all__ = [
    "KNOWN_IMAGE_EXTENSIONS",
    "KNOWN_IMAGE_MIME_TYPES_BY_EXTENSION",
    "_BASE64_PATTERN",
    "_DATA_URI_PATTERN",
    "_IMAGE_KEYS",
    "_is_image_string",
    "image_file_extension_for_mime_type",
    "image_mime_type_for_file_extension",
    "image_ref_file_extension",
    "normalize_image_url_ref",
    "normalize_screenshot_ref",
    "normalize_stored_image_ref",
    "report_image_asset_path",
]
