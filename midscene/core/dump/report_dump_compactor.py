"""Report dump reading/compaction (upstream dump/report-dump-compactor.ts).

Reads the embedded report dump from a report HTML, deduplicates executions by
id (keeping the latest state) and merges multiple reports into one HTML report.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from midscene.core.dump.report_action_dump import get_report_file_name
from midscene.core.report import write_report_html
from midscene.shared.env import get_midscene_run_dir

_REPORT_DUMP_PATTERN = re.compile(
    r'<script id="midscene_report_dump" type="application/json">(.*?)</script>',
    re.DOTALL,
)

_DUMP_HEADER_KEYS = (
    "sdkVersion",
    "groupName",
    "groupDescription",
    "modelBriefs",
    "deviceType",
)


def resolve_report_html_path(html_path: str) -> Path:
    """Accept a report HTML file or a directory containing index.html."""
    path = Path(html_path)
    if not path.exists():
        raise ValueError(f"report-tool: --htmlPath does not exist: {html_path}")
    if path.is_dir():
        index = path / "index.html"
        if not index.exists():
            raise ValueError(
                f'report-tool: "{html_path}" is not an HTML report file, and no '
                "index.html was found under this directory."
            )
        return index
    return path


def read_report_dump(html_path: str) -> Dict[str, Any]:
    """Extract the embedded report dump JSON from a Midscene report HTML."""
    path = resolve_report_html_path(html_path)
    content = path.read_text(encoding="utf-8")
    match = _REPORT_DUMP_PATTERN.search(content)
    if not match:
        raise ValueError(f"No report dump found in {path}")
    try:
        dump = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid report dump JSON in {path}: {e}") from e
    if not isinstance(dump, dict):
        raise ValueError(f"Report dump in {path} must be a mapping")
    return dump


def _dedupe_executions(executions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate executions by id, keeping the latest entry; id-less
    executions are always kept (upstream dedupeExecutionsKeepLatest)."""
    latest: Dict[str, int] = {}
    for index, execution in enumerate(executions):
        if isinstance(execution, dict) and execution.get("id"):
            latest[execution["id"]] = index
    result = []
    for index, execution in enumerate(executions):
        execution_id = execution.get("id") if isinstance(execution, dict) else None
        if execution_id and latest.get(execution_id) != index:
            continue
        result.append(execution)
    return result


def collect_report_executions(
    html_path: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    dump = read_report_dump(html_path)
    executions = dump.get("executions") or []
    if not isinstance(executions, list):
        raise ValueError(f"Report executions in {html_path} must be an array")
    return dump, _dedupe_executions(executions)


def merge_report_files(
    html_paths: List[str],
    output_dir: Optional[str] = None,
    output_name: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, str]:
    """Merge multiple report HTMLs into one HTML report."""
    if not html_paths:
        raise ValueError("mergeReportFiles: htmlPaths is required")

    executions: List[Dict[str, Any]] = []
    base_dump: Optional[Dict[str, Any]] = None
    for html_path in html_paths:
        dump, current = collect_report_executions(html_path)
        if base_dump is None:
            base_dump = dump
        executions.extend(current)
    executions = _dedupe_executions(executions)

    target_dir = Path(output_dir or get_midscene_run_dir("report"))
    target_dir.mkdir(parents=True, exist_ok=True)
    name = (
        get_report_file_name("merged-report")
        if not output_name or output_name == "AUTO"
        else output_name
    )
    output_path = target_dir / f"{name}.html"
    if output_path.exists() and not overwrite:
        raise ValueError(
            f"Report file already exists: {output_path}\n"
            "Set overwrite to true to overwrite this file."
        )

    # Preserve every top-level key from the base dump (including custom report
    # attributes), only replacing the executions list with the merged set.
    merged: Dict[str, Any] = dict(base_dump)
    merged["executions"] = executions
    result = write_report_html(merged, name, str(target_dir))
    if not result:
        raise ValueError("mergeReportFiles: failed to produce a merged report")
    return {"mergedReportPath": result}


__all__ = [
    "_DUMP_HEADER_KEYS",
    "_REPORT_DUMP_PATTERN",
    "_dedupe_executions",
    "collect_report_executions",
    "merge_report_files",
    "read_report_dump",
    "resolve_report_html_path",
]
