"""Directory report artifact reading (upstream dump/report-artifact-reader.ts).

Reads the manifest plus every execution dump of a directory report and can
merge that back into one in-memory dump for export.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from midscene.core.dump.report_artifact_store import (
    ReportArtifactError,
    validate_manifest,
)


def _load_report_dump_for_export(input_path: Path) -> Dict[str, Any]:
    """Read a directory artifact or a single-file HTML report into one dump."""
    from midscene.core.dump.report_dump_compactor import (
        _dedupe_executions,
        read_report_dump,
    )
    from midscene.core.dump.screenshot_restoration import _inline_file_images

    if input_path.is_dir() and (input_path / "report.json").exists():
        artifact = read_report_artifact(input_path)
        if not artifact["executions"]:
            raise ReportArtifactError(
                "No report execution data was found in the input."
            )
        dumps = [
            _inline_file_images(
                entry["dump"],
                [input_path / Path(entry["path"]).parent, input_path],
            )
            for entry in artifact["executions"]
        ]
        merged = dict(dumps[0])
        executions: List[Dict[str, Any]] = []
        for dump in dumps:
            executions.extend(dump.get("executions") or [])
        merged["executions"] = _dedupe_executions(executions)
        if artifact.get("runner"):
            merged["runner"] = artifact["runner"]
        return merged
    try:
        dump = read_report_dump(str(input_path))
    except ValueError as error:
        raise ReportArtifactError(str(error)) from error
    return _inline_file_images(dump, [input_path.parent])


def read_report_artifact(root: Union[str, Path]) -> Dict[str, Any]:
    """Read the manifest plus every execution dump of a directory report."""
    base = Path(root)
    manifest_path = base / "report.json"
    if not manifest_path.exists():
        raise ReportArtifactError(f"No report artifact manifest at {manifest_path}")
    manifest = validate_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    executions: List[Dict[str, Any]] = []
    for group in manifest["groups"]:
        for dump_path in group["dumps"]:
            executions.append(
                {
                    "group": group["id"],
                    "path": dump_path,
                    "dump": json.loads(
                        (base / dump_path).read_text(encoding="utf-8")
                    ),
                }
            )
    runner = None
    if manifest.get("runner"):
        runner_path = base / manifest["runner"]
        if runner_path.exists():
            runner = json.loads(runner_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "executions": executions, "runner": runner}


__all__ = [
    "_load_report_dump_for_export",
    "read_report_artifact",
]
