"""Screenshot reference helpers (upstream dump/screenshot-store.ts).

Only the validation/normalization and inline-image extraction pieces are
ported; the upstream `ReportImageStore` writes files while reports are
produced, which the Python SDK does inside `screenshot_restoration` instead.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Optional

from midscene.core.dump.html_utils import anti_escape_script_tag
from midscene.core.dump.image_reference import (
    image_file_extension_for_mime_type,
    image_ref_file_extension,
    normalize_stored_image_ref,
)

SCREENSHOT_REF_TYPE = "midscene_screenshot_ref"

_IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$", re.IGNORECASE)

_BASE64_IMAGE_DATA_URL_PATTERN = re.compile(
    r"^data:(image/[a-z0-9.+-]+)(?:;[^,]*)?;base64,([a-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


def detect_format(base64_data: str) -> str:
    if base64_data.startswith("data:image/jpeg"):
        return "jpeg"
    if base64_data.startswith("data:image/jpg"):
        return "jpeg"
    return "png"


def _has_valid_storage(record: Dict[str, Any]) -> bool:
    if record.get("storage") not in ("inline", "file"):
        return False
    return record.get("storage") != "file" or isinstance(record.get("path"), str)


def normalize_screenshot_ref(value: Any) -> Optional[Dict[str, Any]]:
    """Validate and normalize a serialized screenshot reference."""
    if not isinstance(value, dict):
        return None
    if (
        value.get("type") == SCREENSHOT_REF_TYPE
        and isinstance(value.get("id"), str)
        and _IMAGE_ID_PATTERN.match(value["id"])
        and isinstance(value.get("capturedAt"), (int, float))
        and not isinstance(value.get("capturedAt"), bool)
        and value.get("mimeType") in ("image/png", "image/jpeg")
        and _has_valid_storage(value)
    ):
        return value
    return None


def extract_image_by_id_sync(html_path: str, image_id: str) -> Optional[str]:
    """Extract an inline `<script type="midscene-image">` payload by id."""
    html = Path(html_path).read_text(encoding="utf-8")
    pattern = re.compile(
        r'<script type="midscene-image" data-id="'
        + re.escape(image_id)
        + r'">(.*?)</script>',
        re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        return None
    return anti_escape_script_tag(match.group(1))


def parse_base64_image_data_url(image_url: str) -> Dict[str, str]:
    """Parse and normalize a base64 image data URL for report persistence."""
    match = _BASE64_IMAGE_DATA_URL_PATTERN.match(image_url)
    if not match:
        raise ValueError(
            "ReportImageStore: reference image must be a valid base64 image data URL"
        )
    mime_type = match.group(1).lower()
    return {
        "mimeType": mime_type,
        "extension": image_file_extension_for_mime_type(mime_type),
        "rawBase64": re.sub(r"\s", "", match.group(2)),
    }


def is_base64_image_data_url(value: str) -> bool:
    return bool(_BASE64_IMAGE_DATA_URL_PATTERN.match(value))


def report_image_file_name(extension: str, data: bytes) -> str:
    """Stable asset names allow different observations to share the same bytes."""
    digest = hashlib.sha256()
    digest.update(extension.encode())
    digest.update(b"\0")
    digest.update(data)
    return f"{digest.hexdigest()}.{extension}"


def resolve_image_source(
    ref_input: Any,
    *,
    report_path: str,
    image_directory: Optional[str] = None,
    fallback_id: Optional[str] = None,
    fallback_mime_type: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve any stored report image reference to a data URI or file path."""
    ref = normalize_stored_image_ref(ref_input)
    image_id = ref.get("id") if ref else fallback_id
    mime_type = ref.get("mimeType") if ref else fallback_mime_type
    if not image_id or not mime_type:
        raise ValueError(
            "ReportImageStore: image id and mimeType are required to resolve an image"
        )

    report_dir = Path(report_path).parent

    def _resolve_relative(file_path: str) -> Path:
        path = Path(file_path)
        return path if path.is_absolute() else report_dir / path

    if ref and ref.get("storage") == "file":
        if not ref.get("path"):
            raise ValueError(
                f'ReportImageStore: image ref "{ref["id"]}" missing file path'
            )
        explicit = _resolve_relative(ref["path"])
        if explicit.is_file():
            return {
                "type": "file",
                "id": image_id,
                "mimeType": mime_type,
                "filePath": str(explicit),
            }

    inline_data_uri = extract_image_by_id_sync(report_path, image_id)
    if inline_data_uri:
        return {
            "type": "data-uri",
            "id": image_id,
            "mimeType": mime_type,
            "dataUri": inline_data_uri,
        }

    extension = (
        image_ref_file_extension(ref)
        if ref
        else image_file_extension_for_mime_type(fallback_mime_type or mime_type)
    )
    if image_directory:
        companion = Path(image_directory) / f"{image_id}.{extension}"
        if companion.is_file():
            return {
                "type": "file",
                "id": image_id,
                "mimeType": mime_type,
                "filePath": str(companion),
            }
    sibling = report_dir / "screenshots" / f"{image_id}.{extension}"
    if sibling.is_file():
        return {
            "type": "file",
            "id": image_id,
            "mimeType": mime_type,
            "filePath": str(sibling),
        }

    raise ValueError(
        f'ReportImageStore: cannot resolve image "{image_id}" from {report_path}'
    )


__all__ = [
    "SCREENSHOT_REF_TYPE",
    "detect_format",
    "extract_image_by_id_sync",
    "is_base64_image_data_url",
    "normalize_screenshot_ref",
    "parse_base64_image_data_url",
    "report_image_file_name",
    "resolve_image_source",
]
