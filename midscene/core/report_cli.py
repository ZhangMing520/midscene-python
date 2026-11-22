"""Report CLI helpers: read / split / merge (upstream core/src/report-cli.ts).

The implementation lives in `midscene.core.dump.report_dump_compactor` and
`midscene.core.dump.test_report_images`; this module re-exports the original
names so existing imports keep working.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from midscene.core.dump.report_dump_compactor import (
    _DUMP_HEADER_KEYS,
    _REPORT_DUMP_PATTERN,
    _dedupe_executions,
    collect_report_executions,
    merge_report_files,
    read_report_dump,
    resolve_report_html_path,
)
from midscene.core.dump.test_report_images import split_report_file

def report_file_to_markdown(options: Dict[str, Any]) -> Dict[str, List[str]]:
    """Convert a report file to Markdown (upstream reportFileToMarkdown)."""
    from midscene.core.report_markdown import (
        report_file_to_markdown as _report_file_to_markdown,
    )

    html_path = options.get("htmlPath") or options.get("html_path")
    output_dir = options.get("outputDir") or options.get("output_dir")
    if not html_path:
        raise ValueError("reportFileToMarkdown: htmlPath is required")
    if not output_dir:
        raise ValueError("reportFileToMarkdown: outputDir is required")
    return _report_file_to_markdown(
        resolve_report_html_path(html_path), output_dir
    )


REPORT_TOOL_ACTIONS = ("split", "to-markdown", "merge-html", "export")


@dataclass(frozen=True)
class ReportCliCommandDefinition:
    """Equivalent of the upstream `ReportCliCommandDefinition` interface."""

    name: str
    description: str
    schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ReportCliCommandEntry:
    """Equivalent of the upstream `ReportCliCommandEntry` interface."""

    name: str
    definition: ReportCliCommandDefinition = field(repr=False)


def _tool_result(text: str) -> Dict[str, Any]:
    return {"isError": False, "content": [{"type": "text", "text": text}]}


def _is_truthy_flag(value: Any) -> bool:
    return value is True or value == "true" or value == "1"


def _normalize_html_report_arg(raw: Any) -> Optional[List[str]]:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [
            path for path in raw if isinstance(path, str) and len(path) > 0
        ]
    if isinstance(raw, str):
        trimmed = raw.strip()
        return [trimmed] if trimmed else []
    return None


_REPORT_TOOL_SCHEMA: Dict[str, Any] = {
    "action": {
        "type": "enum",
        "values": list(REPORT_TOOL_ACTIONS),
        "description": (
            "Report action to run. Supports: split, to-markdown, merge-html, "
            "export. Defaults to split."
        ),
    },
    "htmlPath": {
        "type": "string",
        "description": (
            "Input report HTML path (e.g. ./report/index.html). Used by "
            "split, to-markdown, and export."
        ),
    },
    "htmlReport": {
        "type": "string | string[]",
        "description": (
            "Input report HTML path for the merge action. Repeat the flag to "
            "merge multiple reports."
        ),
    },
    "outputDir": {
        "type": "string",
        "description": "Output directory for generated report artifacts.",
    },
    "outputName": {
        "type": "string",
        "description": "Output report file/directory name (without .html).",
    },
    "overwrite": {
        "type": "boolean | string",
        "description": "Overwrite an existing output report for merge or export.",
    },
    "outputFormat": {
        "type": "enum",
        "values": ["single-html", "html-and-external-assets"],
        "description": "Final delivery format for merge and export.",
    },
}


async def _handle_report_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    from midscene.core.dump.report_artifact_writer import export_report_artifact
    from midscene.core.report_markdown import report_file_to_markdown

    action = args.get("action") or "split"
    html_path = args.get("htmlPath")
    html_report = args.get("htmlReport")
    output_dir = args.get("outputDir")
    output_name = args.get("outputName")
    overwrite = args.get("overwrite")
    output_format = args.get("outputFormat")

    if action not in REPORT_TOOL_ACTIONS:
        raise ValueError(
            f'report-tool: unsupported --action value "{action}". '
            f"Currently supported: {', '.join(REPORT_TOOL_ACTIONS)}"
        )

    if action == "merge-html":
        paths = _normalize_html_report_arg(html_report)
        if not paths:
            raise ValueError(
                "report-tool: --htmlReport is required for action "
                '"merge-html". Repeat --htmlReport for each report '
                "(e.g. --htmlReport ./a/index.html --htmlReport ./b.html)."
            )
        result = merge_report_files(
            paths,
            output_dir,
            output_name,
            _is_truthy_flag(overwrite),
        )
        return _tool_result(
            f"Merged {len(paths)} report(s) into {result['mergedReportPath']}"
        )

    if not html_path:
        raise ValueError("report-tool: --htmlPath is required")
    if not output_dir:
        raise ValueError("report-tool: --outputDir is required")

    if action == "export":
        input_path = resolve_report_html_path(html_path)
        name = (
            output_name
            or (
                Path(input_path).parent.name
                if Path(input_path).name == "index.html"
                else Path(input_path).stem
            )
        )
        report_path = export_report_artifact(
            input_path,
            output_dir,
            name,
            output_format or "single-html",
            _is_truthy_flag(overwrite),
        )
        return _tool_result(f"Report exported to {report_path}")

    if action == "to-markdown":
        result = report_file_to_markdown(html_path, output_dir)
        return _tool_result(
            "Markdown export completed. Generated "
            f"{len(result['markdownFiles'])} markdown file(s) and "
            f"{len(result['screenshotFiles'])} screenshot(s). "
            f"Output path: {output_dir}"
        )

    result = split_report_file(html_path, output_dir)
    return _tool_result(
        "Report split completed. Generated "
        f"{len(result['executionJsonFiles'])} execution JSON files and "
        f"{len(result['screenshotFiles'])} screenshots. "
        f"Output path: {output_dir}"
    )


_REPORT_TOOL_DEFINITION = ReportCliCommandDefinition(
    name="report-tool",
    description=(
        "Transform Midscene report artifacts, including splitting executions, "
        "converting to markdown, merging multiple reports, and exporting "
        "portable reports in either storage format."
    ),
    schema=_REPORT_TOOL_SCHEMA,
    handler=_handle_report_tool,
)


def create_report_cli_commands() -> List[ReportCliCommandEntry]:
    """Return the generic report command (upstream createReportCliCommands)."""
    return [
        ReportCliCommandEntry(
            name="report-tool", definition=_REPORT_TOOL_DEFINITION
        )
    ]


__all__ = [
    "REPORT_TOOL_ACTIONS",
    "ReportCliCommandDefinition",
    "ReportCliCommandEntry",
    "_DUMP_HEADER_KEYS",
    "_REPORT_DUMP_PATTERN",
    "_dedupe_executions",
    "collect_report_executions",
    "create_report_cli_commands",
    "merge_report_files",
    "read_report_dump",
    "report_file_to_markdown",
    "resolve_report_html_path",
    "split_report_file",
]
