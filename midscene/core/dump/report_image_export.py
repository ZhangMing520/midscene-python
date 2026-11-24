"""Export report image bytes once (upstream dump/report-image-export.ts)."""

import base64
from pathlib import Path
from typing import Any

from midscene.core.dump.image_reference import image_ref_file_extension
from midscene.core.dump.screenshot_store import (
    parse_base64_image_data_url,
    report_image_file_name,
    resolve_image_source,
)


class ReportImageExporter:
    """Export image bytes once while keeping every observation's own metadata."""

    def __init__(self, report_path: str, screenshots_dir: str):
        self.report_path = report_path
        self.screenshots_dir = Path(screenshots_dir)
        self._locations: dict[str, str] = {}
        self._written_files: set[str] = set()

    def write(self, ref: dict[str, Any], data_uri: str | None = None) -> str:
        key = repr(
            [ref.get("id"), ref.get("mimeType"), ref.get("storage"), ref.get("path")]
        )
        known = self._locations.get(key)
        if known:
            return known
        source: dict[str, str]
        if data_uri:
            source = {"type": "data-uri", "dataUri": data_uri}
        else:
            source = resolve_image_source(ref, report_path=self.report_path)
        if source["type"] == "file":
            data = Path(source["filePath"]).read_bytes()
        else:
            data = base64.b64decode(
                parse_base64_image_data_url(source["dataUri"])["rawBase64"]
            )
        name = report_image_file_name(image_ref_file_extension(ref), data)
        if name not in self._written_files:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            (self.screenshots_dir / name).write_bytes(data)
            self._written_files.add(name)
        self._locations[key] = name
        return name

    @property
    def files(self) -> list[str]:
        return [
            str(self.screenshots_dir / name) for name in sorted(self._written_files)
        ]


__all__ = ["ReportImageExporter"]
