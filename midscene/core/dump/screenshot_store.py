"""Screenshot reference helpers (upstream dump/screenshot-store.ts).

Only the validation/normalization and inline-image extraction pieces are
ported; the upstream `ReportImageStore` writes files while reports are
produced, which the Python SDK does inside `screenshot_restoration` instead.
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional

from midscene.core.dump.html_utils import anti_escape_script_tag

SCREENSHOT_REF_TYPE = "midscene_screenshot_ref"

_IMAGE_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,128}$", re.IGNORECASE)


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


__all__ = [
    "SCREENSHOT_REF_TYPE",
    "detect_format",
    "extract_image_by_id_sync",
    "normalize_screenshot_ref",
]
