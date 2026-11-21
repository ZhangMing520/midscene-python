"""Markdown report rendering (upstream core/src/report-markdown.ts)."""

from typing import Any, Dict, List
import json
from pathlib import Path

from midscene.core.report import _externalize_images
from midscene.core.report_cli import (
    _DUMP_HEADER_KEYS,
    collect_report_executions,
)

def _format_json(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def _collect_file_images(value: Any) -> List[str]:
    paths: List[str] = []
    if isinstance(value, dict):
        if value.get("storage") == "file" and isinstance(value.get("path"), str):
            paths.append(value["path"])
        else:
            for item in value.values():
                paths.extend(_collect_file_images(item))
    elif isinstance(value, list):
        for item in value:
            paths.extend(_collect_file_images(item))
    return paths


def _execution_status(execution: Dict[str, Any]) -> str:
    tasks = execution.get("tasks") or []
    for task in tasks:
        if isinstance(task, dict) and task.get("status") in ("failed", "cancelled"):
            return "failed"
    return "success"


def report_to_markdown(dump: Dict[str, Any]) -> str:
    """Render a report dump as Markdown (upstream reportToMarkdown subset)."""
    lines: List[str] = []
    group_name = str(dump.get("groupName") or "Midscene Report")
    lines.append(f"# {group_name}")
    lines.append("")
    description = dump.get("groupDescription")
    if description:
        lines.append(str(description))
        lines.append("")
    lines.append(f"- SDK version: {dump.get('sdkVersion', '?')}")
    lines.append(f"- Device type: {dump.get('deviceType', '-')}")
    executions = dump.get("executions") or []
    lines.append(f"- Executions: {len(executions)}")
    lines.append("")

    for index, execution in enumerate(executions, 1):
        name = execution.get("name") or execution.get("id") or f"execution {index}"
        lines.append(f"## {index}. {name}")
        lines.append("")
        lines.append(f"- Status: {_execution_status(execution)}")
        if execution.get("description"):
            lines.append(f"- Description: {execution['description']}")
        if execution.get("logTime") is not None:
            lines.append(f"- Log time: {execution['logTime']}")
        lines.append("")

        for task in execution.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_type = task.get("type") or "Task"
            sub_type = f" / {task['subType']}" if task.get("subType") else ""
            status = task.get("status") or "finished"
            lines.append(f"### {task_type}{sub_type} — {status}")
            lines.append("")
            if task.get("param") not in (None, {}, []):
                lines.append("**Param**")
                lines.append("")
                lines.append(_format_json(task["param"]))
                lines.append("")
            if task.get("output") not in (None, {}, []):
                lines.append("**Output**")
                lines.append("")
                lines.append(_format_json(task["output"]))
                lines.append("")
            if task.get("errorMessage"):
                lines.append(f"**Error**: {task['errorMessage']}")
                lines.append("")
            for image_path in _collect_file_images(task):
                lines.append(f"![screenshot]({image_path})")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def report_file_to_markdown(
    html_path: str, output_dir: str
) -> Dict[str, List[str]]:
    """Convert a report HTML into report.md plus externalized screenshots."""
    dump, executions = collect_report_executions(html_path)
    out_dir = Path(output_dir)
    screenshots_dir = out_dir / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: set = set()
    processed = [
        _externalize_images(
            execution, None, screenshots_dir, written, {"counter": 0}, f"execution-{index}"
        )
        for index, execution in enumerate(executions, 1)
    ]
    merged = {key: dump[key] for key in _DUMP_HEADER_KEYS if key in dump}
    merged["executions"] = processed

    md_path = out_dir / "report.md"
    md_path.write_text(report_to_markdown(merged), encoding="utf-8")
    return {
        "markdownFiles": [str(md_path)],
        "screenshotFiles": [str(screenshots_dir / name) for name in sorted(written)],
    }
