"""Write CLI screenshots to disk (upstream cli/screenshot-file.ts)."""

import base64
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

_SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]")


def _safe_screenshot_filename_part(value: Any) -> str:
    text = value if isinstance(value, str) and value else "shot"
    sanitized = _SAFE_FILENAME_PATTERN.sub("_", text)
    return sanitized or "shot"


def _extension_from_image_metadata(
    mime_type: Any, extension: Any
) -> str:
    if extension in ("jpeg", "jpg"):
        return "jpeg"
    if extension == "png":
        return "png"
    return "jpeg" if mime_type == "image/jpeg" else "png"


def write_cli_screenshot_file(
    raw_base64: str, options: Optional[Dict[str, Any]] = None
) -> str:
    options = options or {}
    extension = _extension_from_image_metadata(
        options.get("mimeType"), options.get("extension")
    )
    directory_path = options.get("directoryPath")
    directory_name = options.get("directoryName")
    directory = (
        Path(directory_path)
        if directory_path
        else (
            Path(tempfile.gettempdir()) / directory_name
            if directory_name
            else Path(tempfile.gettempdir())
        )
    )
    directory.mkdir(parents=True, exist_ok=True)

    now_ms = int(time.time() * 1000)
    if options.get("id") is not None:
        filename = f"{_safe_screenshot_filename_part(options['id'])}.{extension}"
    else:
        prefix = options.get("filenamePrefix") or "screenshot"
        filename = f"{prefix}-{now_ms}.{extension}"

    file_path = directory / filename
    overwrite = options.get("overwrite", True)
    if overwrite is not False or not file_path.exists():
        file_path.write_bytes(base64.b64decode(raw_base64))

    return str(file_path)


__all__ = ["write_cli_screenshot_file"]
