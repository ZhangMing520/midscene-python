"""Serialized report image references (upstream dump/image-reference.ts).

The Python SDK stores images either inline (data URI / base64 strings in the
dump) or as files next to the report. These helpers decide which strings are
image payloads when a dump is externalized.
"""

import re
from typing import Optional

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


def _is_image_string(value: str, key: Optional[str]) -> bool:
    if value.startswith("data:image/"):
        return True
    if not key or key.lower() not in _IMAGE_KEYS:
        return False
    return bool(_BASE64_PATTERN.match(value))


__all__ = [
    "_BASE64_PATTERN",
    "_DATA_URI_PATTERN",
    "_IMAGE_KEYS",
    "_is_image_string",
]
