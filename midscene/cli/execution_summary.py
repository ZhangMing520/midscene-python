"""Batch execution summaries and report tooling.

Upstream packages/cli/src/execution-summary.ts.
"""

from pathlib import Path
from typing import Any, Dict, List

from loguru import logger


def create_not_executed_yaml_result(file_path: str) -> Dict[str, Any]:
    """Result for a file skipped because an earlier task failed."""
    return {
        "file": file_path,
        "success": False,
        "executed": False,
        "resultType": "notExecuted",
    }


def get_result_files_by_type(
    results: List[Dict[str, Any]], result_type: str
) -> List[str]:
    """Files whose resultType matches `result_type`."""
    return [r["file"] for r in results if r.get("resultType") == result_type]


def is_batch_successful(
    results: List[Dict[str, Any]], hook_error: Any = None
) -> bool:
    """A batch passed when no lifecycle hook failed and every file succeeded."""
    return hook_error is None and all(r["success"] for r in results)


def write_execution_summary_file(summary_path: Any, results: List[Dict[str, Any]]) -> None:
    """Write the JSON execution summary when a summary path is configured."""
    if not summary_path:
        return
    import json as _json

    Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_path).write_text(
        _json.dumps(
            [{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(f"Batch summary written to {summary_path}")


def run_report_tool(
    console,
    action: str,
    html_path,
    html_report,
    output_dir,
    output_name,
    overwrite: bool,
) -> bool:
    """Transform Midscene report artifacts (upstream `midscene report-tool`)."""
    from midscene.core.report_cli import (
        merge_report_files,
        split_report_file,
    )
    from midscene.core.report_markdown import report_file_to_markdown

    if action not in ("split", "to-markdown", "merge-html"):
        console.print(
            f'[red]report-tool: unsupported --action value "{action}". '
            "Currently supported: split, to-markdown, merge-html[/red]"
        )
        return False

    try:
        if action == "merge-html":
            if not html_report:
                console.print(
                    "[red]report-tool: --htmlReport is required for action "
                    '"merge-html".[/red]'
                )
                return False
            result = merge_report_files(
                html_report, output_dir, output_name, overwrite
            )
            console.print(
                f"Merged {len(html_report)} report(s) into "
                f"{result['mergedReportPath']}"
            )
            return True

        if not html_path:
            console.print("[red]report-tool: --htmlPath is required[/red]")
            return False
        if not output_dir:
            console.print("[red]report-tool: --outputDir is required[/red]")
            return False

        if action == "to-markdown":
            result = report_file_to_markdown(html_path, output_dir)
            console.print(
                "Markdown export completed. Generated "
                f"{len(result['markdownFiles'])} markdown file(s) and "
                f"{len(result['screenshotFiles'])} screenshot(s). "
                f"Output path: {output_dir}"
            )
            return True

        result = split_report_file(html_path, output_dir)
        console.print(
            "Report split completed. Generated "
            f"{len(result['executionJsonFiles'])} execution JSON files and "
            f"{len(result['screenshotFiles'])} screenshots. "
            f"Output path: {output_dir}"
        )
        return True
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return False
