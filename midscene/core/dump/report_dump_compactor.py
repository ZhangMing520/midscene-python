"""Report dump reading/compaction (upstream dump/report-dump-compactor.ts).

Reads the embedded report dump from a report HTML, deduplicates executions by
id (keeping the latest state) and merges multiple reports into one HTML report.
"""

import json
import os
import re
import uuid
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


def compact_report_dumps(report_path: str) -> Dict[str, Any]:
    """Merge repeated dump scripts per group, keeping the latest executions.

    Upstream streams the file in chunks; the Python report is a text document,
    so the same rewrite runs on the decoded HTML. Directory reports have no
    inline scripts to compact and are returned unchanged.
    """
    from midscene.core.dump.html_utils import (
        anti_escape_script_tag,
        escape_script_tag,
    )
    from midscene.core.dump.report_artifact_reader import read_report_dump_scripts

    path = Path(report_path)
    before = path.stat()
    dump_scripts = read_report_dump_scripts(path)
    if not dump_scripts:
        return {
            "beforeBytes": before.st_size,
            "afterBytes": before.st_size,
            "beforeDumpCount": 0,
            "afterDumpCount": 0,
        }

    group_re = re.compile(r'data-group-id="([^"]+)"')
    groups: Dict[str, Dict[str, Any]] = {}
    tag_count = 0
    for script in dump_scripts:
        match = group_re.search(script["openTag"])
        if not match:
            continue
        group_id = match.group(1)
        group = groups.setdefault(
            group_id,
            {
                "baseDump": None,
                "executionsByKey": {},
                "firstOpenTag": script["openTag"],
                "noIdExecutionIndex": 0,
                "tagCount": 0,
            },
        )
        dump = json.loads(anti_escape_script_tag(script["content"]).strip())
        if group["baseDump"] is None:
            group["baseDump"] = dump
        group["tagCount"] += 1
        tag_count += 1
        for execution in dump.get("executions") or []:
            execution_key = (
                f"id:{execution['id']}"
                if execution.get("id")
                else f"no-id:{group['noIdExecutionIndex']}"
            )
            if not execution.get("id"):
                group["noIdExecutionIndex"] += 1
            group["executionsByKey"][execution_key] = execution

    after_dump_count = len(groups)
    if tag_count <= after_dump_count:
        return {
            "beforeBytes": before.st_size,
            "afterBytes": before.st_size,
            "beforeDumpCount": tag_count,
            "afterDumpCount": after_dump_count,
        }

    compacted_tags: Dict[str, str] = {}
    for group_id, group in groups.items():
        base_dump = dict(group["baseDump"] or {})
        base_dump["executions"] = list(group["executionsByKey"].values())
        compacted_tags[group_id] = (
            f"{group['firstOpenTag']}"
            f"{escape_script_tag(json.dumps(base_dump, ensure_ascii=False))}"
            "</script>"
        )

    html = path.read_text(encoding="utf-8")
    script_re = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL)
    seen_tags_by_group: Dict[str, int] = {}
    output: List[str] = []
    last_index = 0

    for match in script_re.finditer(html):
        open_tag_end = match.start() + html[match.start() :].find(">") + 1
        open_tag = html[match.start() : open_tag_end]
        group_match = group_re.search(open_tag)
        if not group_match or group_match.group(1) not in groups:
            continue
        group_id = group_match.group(1)
        output.append(html[last_index : match.start()])
        seen_count = seen_tags_by_group.get(group_id, 0) + 1
        seen_tags_by_group[group_id] = seen_count
        if seen_count == groups[group_id]["tagCount"]:
            output.append(compacted_tags[group_id])
        last_index = match.end()

    output.append(html[last_index:])
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_text("".join(output), encoding="utf-8")
        after = temporary_path.stat()
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise

    return {
        "beforeBytes": before.st_size,
        "afterBytes": after.st_size,
        "beforeDumpCount": tag_count,
        "afterDumpCount": after_dump_count,
    }


__all__ = [
    "_DUMP_HEADER_KEYS",
    "_REPORT_DUMP_PATTERN",
    "_dedupe_executions",
    "collect_report_executions",
    "compact_report_dumps",
    "merge_report_files",
    "read_report_dump",
    "resolve_report_html_path",
]
