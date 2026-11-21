"""Lazy screenshot container (upstream core/src/screenshot-item.ts).

After a report persists an image, base64 memory can be released while the
screenshot remains recoverable from the HTML (inline mode) or a file. The
reference normalization/extraction helpers live in
`midscene.core.dump.screenshot_store` and are re-exported here.
"""

import base64
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from midscene.core.dump.screenshot_store import (
    SCREENSHOT_REF_TYPE,
    detect_format,
    extract_image_by_id_sync,
    normalize_screenshot_ref,
)


class ScreenshotItem:
    """Screenshot data with lazy recovery after memory release."""

    _is_screenshot_item = True

    def __init__(
        self,
        id: str,
        base64_data: Optional[str],
        captured_at: int,
        image_format: str,
    ) -> None:
        self._id = id
        self._base64 = base64_data
        self._format = image_format
        self._captured_at = captured_at
        self._serialized_ref: Optional[Dict[str, Any]] = None
        self._persisted_path: Optional[str] = None
        self._persisted_html_path: Optional[str] = None

    @staticmethod
    def is_screenshot_item(value: Any) -> bool:
        return (
            value is not None
            and getattr(value, "_is_screenshot_item", False) is True
        )

    @classmethod
    def create(cls, base64_data: str, captured_at: int) -> "ScreenshotItem":
        return cls(uuid.uuid4().hex, base64_data, captured_at, detect_format(base64_data))

    @classmethod
    def from_file(
        cls, file_path: str, mime_type: str, captured_at: int
    ) -> "ScreenshotItem":
        item = cls(
            uuid.uuid4().hex,
            None,
            captured_at,
            "jpeg" if mime_type == "image/jpeg" else "png",
        )
        item._persisted_path = file_path
        return item

    @property
    def id(self) -> str:
        return self._id

    @property
    def format(self) -> str:
        return self._format

    @property
    def extension(self) -> str:
        return "jpeg" if self._format == "jpeg" else "png"

    @property
    def captured_at(self) -> int:
        return self._captured_at

    def _load_from_file(self) -> str:
        if self._persisted_path is None:
            raise RuntimeError(f"Screenshot {self._id}: file recovery path missing")
        data = Path(self._persisted_path).read_bytes()
        return f"data:image/{self._format};base64,{base64.b64encode(data).decode()}"

    def _load_from_inline(self) -> str:
        if self._persisted_html_path is None:
            raise RuntimeError(f"Screenshot {self._id}: HTML recovery path missing")
        data = extract_image_by_id_sync(self._persisted_html_path, self._id)
        if data:
            return data
        raise RuntimeError(
            f"Screenshot {self._id}: cannot recover from HTML "
            f"(id not found in {self._persisted_html_path})"
        )

    @property
    def base64(self) -> str:
        if self._base64 is not None:
            return self._base64
        if self._serialized_ref is not None:
            if self._serialized_ref.get("storage") == "file":
                return self._load_from_file()
            if self._serialized_ref.get("storage") == "inline":
                return self._load_from_inline()
        if self._persisted_path is not None:
            return self._load_from_file()
        if self._persisted_html_path is not None:
            return self._load_from_inline()
        raise RuntimeError(
            f"Screenshot {self._id}: base64 data released without recovery path"
        )

    def retain_for_recording(self) -> None:
        """Retain a borrowed file-backed image before its temporary owner is released."""
        if self._base64 is not None or self._serialized_ref is not None:
            return
        self._base64 = self.base64
        self._persisted_path = None

    def has_base64(self) -> bool:
        return self._base64 is not None

    def _create_ref(self, storage: str, relative_path: Optional[str] = None) -> Dict[str, Any]:
        ref: Dict[str, Any] = {
            "type": SCREENSHOT_REF_TYPE,
            "id": self._id,
            "capturedAt": self._captured_at,
            "mimeType": "image/jpeg" if self._format == "jpeg" else "image/png",
            "storage": storage,
        }
        if storage == "file":
            ref["path"] = relative_path
        return ref

    def mark_persisted_inline(self, html_path: str) -> Dict[str, Any]:
        ref = self._create_ref("inline")
        self._serialized_ref = ref
        self._persisted_html_path = html_path
        self._base64 = None
        return ref

    def register_persisted_file_copy(
        self, relative_path: str, absolute_path: str
    ) -> Dict[str, Any]:
        ref = self._create_ref("file", relative_path)
        self._persisted_path = absolute_path
        self._base64 = None
        return ref

    def mark_persisted_to_path(
        self, relative_path: str, absolute_path: str
    ) -> Dict[str, Any]:
        ref = self.register_persisted_file_copy(relative_path, absolute_path)
        self._serialized_ref = ref
        return ref

    def to_serializable(self) -> Dict[str, Any]:
        return self._serialized_ref or {
            "type": SCREENSHOT_REF_TYPE,
            "id": self._id,
            "capturedAt": self._captured_at,
            "mimeType": "image/jpeg" if self._format == "jpeg" else "image/png",
            "storage": "inline",
        }

    @staticmethod
    def is_serialized(value: Any) -> bool:
        return normalize_screenshot_ref(value) is not None

    @property
    def raw_base64(self) -> str:
        return re.sub(
            r"^data:image/(png|jpeg|jpg);base64,", "", self.base64
        )


__all__ = [
    "SCREENSHOT_REF_TYPE",
    "ScreenshotItem",
    "detect_format",
    "extract_image_by_id_sync",
    "normalize_screenshot_ref",
]
