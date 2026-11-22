"""Report image persistence and lookups (upstream dump/screenshot-store.ts).

`ReportImageStore` (aliased as the deprecated `ScreenshotStore`) persists
observations and multimodal prompt images either inline in the report HTML or
as content-addressed files next to it, and resolves serialized references back
to data URIs.
"""

import base64
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from midscene.core.dump.html_utils import (
    anti_escape_script_tag,
    stream_inline_report_images,
)
from midscene.core.dump.image_reference import (
    image_file_extension_for_mime_type,
    image_ref_file_extension,
    normalize_image_url_ref,
    normalize_stored_image_ref,
)
from midscene.core.dump.report_artifact_store import write_report_artifact_file

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
    options: Optional[Dict[str, Any]] = None,
    *,
    report_path: Optional[str] = None,
    image_directory: Optional[str] = None,
    fallback_id: Optional[str] = None,
    fallback_mime_type: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve any stored report image reference to a data URI or file path.

    ``options`` mirrors the upstream options object (``reportPath``,
    ``imageDirectory``, ``fallbackId``, ``fallbackMimeType``); the keyword
    arguments are the Python-friendly equivalent.
    """
    options = options or {}
    report_path = options.get("reportPath", report_path)
    image_directory = options.get("imageDirectory", image_directory)
    fallback_id = options.get("fallbackId", fallback_id)
    fallback_mime_type = options.get("fallbackMimeType", fallback_mime_type)
    if not report_path:
        raise ValueError(
            "ReportImageStore: reportPath is required to resolve an image"
        )
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


def resolve_screenshot_source(
    ref_input: Any,
    options: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, str]:
    """Resolve a serialized screenshot reference to a data URI or file path."""
    return resolve_image_source(
        normalize_screenshot_ref(ref_input), options, **kwargs
    )


def _collect_image_script_ids(file_path: str) -> List[str]:
    """Collect the inline `<script type="midscene-image">` ids in a report."""
    image_ids: List[str] = []

    def visit(image_id: str, _data: str) -> bool:
        image_ids.append(image_id)
        return False

    stream_inline_report_images(file_path, visit)
    return image_ids


class ReportImageStore:
    """Persist and restore every image asset referenced by a report."""

    def __init__(
        self,
        mode: str,
        report_path: Union[str, Path],
        screenshots_dir: Optional[Union[str, Path]] = None,
        write_inline_image: Optional[Callable[[str, str], None]] = None,
        also_write_file_copy: bool = False,
        ensure_file_copy: bool = False,
        reuse_existing_report: bool = False,
    ) -> None:
        self.mode = mode
        self.report_path = str(report_path)
        self.screenshots_dir = (
            Path(screenshots_dir) if screenshots_dir is not None else None
        )
        self.write_inline_image = write_inline_image
        # `ensureFileCopy` is the deprecated alias for `alsoWriteFileCopy`.
        self.also_write_file_copy = bool(
            also_write_file_copy or ensure_file_copy
        )
        self.should_reuse_existing_inline_report = bool(
            reuse_existing_report and mode == "inline"
        )
        self._written_inline_ids: set = set()
        self._written_file_ids: set = set()
        self._file_locations: Dict[str, Dict[str, str]] = {}
        self._existing_inline_image_ids_loaded = False

    def enable_file_copies(self) -> None:
        self.also_write_file_copy = True

    def get_file_path(self, image_id: str) -> str:
        """Resolve an observation/reference id to its content-addressed asset."""
        location = self._file_locations.get(image_id)
        if not location:
            raise ValueError(
                f"ReportImageStore: image {image_id} has no persisted file"
            )
        return location["relativePath"]

    def persist_file_copy(self, screenshot: Any) -> Dict[str, Any]:
        """Keep diagnostic bytes without changing the report location."""
        return self._persist_to_shared_file_if_needed(
            screenshot, mark_as_persisted=False
        )

    def persist(self, screenshot: Any) -> Dict[str, Any]:
        self._ensure_existing_inline_image_ids_loaded()
        should_write_file_copy = (
            self.mode == "directory" or self.also_write_file_copy
        )
        file_ref = (
            self._persist_to_shared_file_if_needed(
                screenshot,
                mark_as_persisted=self.mode == "directory",
            )
            if should_write_file_copy
            else None
        )

        if self.mode == "inline":
            if self.write_inline_image is None:
                raise ValueError(
                    "ReportImageStore: writeInlineImage is required in inline mode"
                )
            if screenshot.id not in self._written_inline_ids:
                self.write_inline_image(screenshot.id, screenshot.base64)
                self._written_inline_ids.add(screenshot.id)
            return screenshot.mark_persisted_inline(self.report_path)

        if not file_ref:
            raise ValueError(
                "ReportImageStore: file persistence is required in directory mode"
            )
        return file_ref

    def persist_reference_image(self, image_url: str) -> Dict[str, Any]:
        """Persist a base64 prompt image and return its content-addressed ref."""
        self._ensure_existing_inline_image_ids_loaded()
        parsed = parse_base64_image_data_url(image_url)
        mime_type = parsed["mimeType"]
        extension = parsed["extension"]
        raw_base64 = parsed["rawBase64"]
        digest = hashlib.sha256()
        digest.update(mime_type.encode())
        digest.update(b"\0")
        digest.update(base64.b64decode(raw_base64))
        image_id = f"reference-{digest.hexdigest()}"

        should_write_file_copy = (
            self.mode == "directory" or self.also_write_file_copy
        )
        file_location = (
            self._write_image_file_if_needed(
                image_id, extension, raw_base64
            )
            if should_write_file_copy
            else None
        )

        if self.mode == "inline":
            if self.write_inline_image is None:
                raise ValueError(
                    "ReportImageStore: writeInlineImage is required in inline mode"
                )
            if image_id not in self._written_inline_ids:
                self.write_inline_image(image_id, image_url)
                self._written_inline_ids.add(image_id)
            return {
                "type": "midscene_image_url_ref",
                "id": image_id,
                "mimeType": mime_type,
                "storage": "inline",
            }

        if not file_location:
            raise ValueError(
                "ReportImageStore: file persistence is required in directory mode"
            )
        return {
            "type": "midscene_image_url_ref",
            "id": image_id,
            "mimeType": mime_type,
            "storage": "file",
            "path": file_location["relativePath"],
        }

    def _ensure_existing_inline_image_ids_loaded(self) -> None:
        if not self.should_reuse_existing_inline_report:
            return
        if self._existing_inline_image_ids_loaded:
            return
        try:
            for image_id in _collect_image_script_ids(self.report_path):
                self._written_inline_ids.add(image_id)
        except FileNotFoundError:
            self._existing_inline_image_ids_loaded = True
            return
        except Exception as error:  # noqa: BLE001 - surface the failing report
            raise ValueError(
                "ReportImageStore: failed to index existing inline images "
                f"from {self.report_path}"
            ) from error
        self._existing_inline_image_ids_loaded = True

    def _persist_to_shared_file_if_needed(
        self,
        screenshot: Any,
        mark_as_persisted: bool,
    ) -> Dict[str, Any]:
        location = self._file_locations.get(screenshot.id) or (
            self._write_image_file_if_needed(
                screenshot.id,
                screenshot.extension,
                screenshot.raw_base64,
            )
        )
        if mark_as_persisted:
            return screenshot.mark_persisted_to_path(
                location["relativePath"], location["absolutePath"]
            )
        return screenshot.register_persisted_file_copy(
            location["relativePath"], location["absolutePath"]
        )

    def _write_image_file_if_needed(
        self, image_id: str, extension: str, raw_base64: str
    ) -> Dict[str, str]:
        if self.screenshots_dir is None:
            raise ValueError(
                "ReportImageStore: screenshotsDir is required when file "
                "persistence is enabled"
            )
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        known = self._file_locations.get(image_id)
        if known:
            return known
        data = base64.b64decode(raw_base64)
        file_name = report_image_file_name(extension, data)
        relative_path = f"./screenshots/{file_name}"
        absolute_path = self.screenshots_dir / file_name
        if file_name not in self._written_file_ids:
            write_report_artifact_file(absolute_path, data)
            self._written_file_ids.add(file_name)
        location = {
            "relativePath": relative_path,
            "absolutePath": str(absolute_path),
        }
        self._file_locations[image_id] = location
        return location

    def load_data_uri(self, ref_input: Any) -> str:
        """Resolve any stored report image reference to a data URI."""
        ref = normalize_stored_image_ref(ref_input)
        if not ref:
            raise ValueError("ReportImageStore: invalid image reference")

        resolved = resolve_image_source(
            ref,
            {
                "reportPath": self.report_path,
                "imageDirectory": (
                    str(self.screenshots_dir)
                    if self.screenshots_dir is not None
                    else None
                ),
            },
        )
        if resolved["type"] == "data-uri":
            return resolved["dataUri"]
        data = Path(resolved["filePath"]).read_bytes()
        return (
            f"data:{resolved['mimeType']};base64,"
            f"{base64.b64encode(data).decode('ascii')}"
        )

    def load_base64(self, ref_input: Any) -> str:
        """Deprecated alias for `load_data_uri` that requires a screenshot ref."""
        screenshot_ref = normalize_screenshot_ref(ref_input)
        if not screenshot_ref:
            raise ValueError(
                "ReportImageStore: invalid screenshot reference"
            )
        return self.load_data_uri(screenshot_ref)

    def cleanup(self) -> None:
        if (
            self.mode == "directory"
            and self.screenshots_dir is not None
            and self.screenshots_dir.exists()
        ):
            shutil.rmtree(self.screenshots_dir, ignore_errors=True)
        self._written_inline_ids.clear()
        self._written_file_ids.clear()
        self._file_locations.clear()
        self._existing_inline_image_ids_loaded = False


# Backward-compatible alias for existing external consumers.
ScreenshotStore = ReportImageStore


__all__ = [
    "SCREENSHOT_REF_TYPE",
    "ReportImageStore",
    "ScreenshotStore",
    "detect_format",
    "extract_image_by_id_sync",
    "image_ref_file_extension",
    "is_base64_image_data_url",
    "normalize_image_url_ref",
    "normalize_screenshot_ref",
    "normalize_stored_image_ref",
    "parse_base64_image_data_url",
    "report_image_file_name",
    "resolve_image_source",
    "resolve_screenshot_source",
]
