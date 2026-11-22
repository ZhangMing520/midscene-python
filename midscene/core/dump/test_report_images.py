"""Split report images (upstream dump/test-report-images.ts).

Splitting one report HTML into per-execution JSON files also externalizes the
inline images next to those files so each execution stays renderable.
"""

import json
from pathlib import Path
from typing import Dict, List

from midscene.core.dump.report_artifact_writer import TestReportImages
from midscene.core.dump.report_dump_compactor import (
    _DUMP_HEADER_KEYS,
    collect_report_executions,
)
from midscene.core.dump.screenshot_restoration import _externalize_images


def split_report_file(html_path: str, output_dir: str) -> Dict[str, List[str]]:
    """Split one report HTML into per-execution JSON files + screenshots."""
    dump, executions = collect_report_executions(html_path)
    out_dir = Path(output_dir)
    screenshots_dir = out_dir / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    execution_json_files: List[str] = []
    written: set = set()
    for index, execution in enumerate(executions, 1):
        processed = _externalize_images(
            execution, None, screenshots_dir, written, {"counter": 0}, f"execution-{index}"
        )
        single = {
            key: dump[key] for key in _DUMP_HEADER_KEYS if key in dump
        }
        single["executions"] = [processed]
        json_path = out_dir / f"{index}.execution.json"
        json_path.write_text(
            json.dumps(single, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        execution_json_files.append(str(json_path))

    return {
        "executionJsonFiles": execution_json_files,
        "screenshotFiles": [str(screenshots_dir / name) for name in sorted(written)],
    }


__all__ = ["TestReportImages", "split_report_file"]
