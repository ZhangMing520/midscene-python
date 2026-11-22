"""Batch execution summaries and report tooling.

Upstream packages/cli/src/execution-summary.ts.
"""

import datetime
import hashlib
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from loguru import logger

from midscene.shared.env import get_midscene_run_dir

_DUMP_SCRIPT_PATTERN = re.compile(
    r'<script[^>]*type="midscene_web_dump"[^>]*>(.*?)</script>', re.DOTALL
)

not_executed_error = "Not executed (previous task failed)"


def create_not_executed_yaml_result(file_path: str) -> Dict[str, Any]:
    """Result for a file skipped because an earlier task failed."""
    return {
        "file": file_path,
        "success": False,
        "executed": False,
        "output": None,
        "report": None,
        "duration": 0,
        "resultType": "notExecuted",
        "error": not_executed_error,
    }


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _player_task_status_list(player: Any) -> List[Dict[str, Any]]:
    statuses = _field(player, "taskStatusList", "task_status_list")
    if isinstance(statuses, list):
        return statuses
    failed_tasks = _field(player, "failedTasks", "failed_tasks", default=[])
    return [
        {"status": "error", "error": task}
        for task in failed_tasks or []
    ]


def _is_player_successful(player: Any) -> bool:
    """True when the player and all of its tasks finished without error."""
    if _field(player, "status", default="done") == "error":
        return False
    statuses = _player_task_status_list(player)
    return not any(
        _field(task, "status", default="done") == "error" for task in statuses
    )


def is_yaml_player_successful(player: Any) -> bool:
    """Whether a YAML player (and every task) succeeded."""
    return _is_player_successful(player)


def _task_error_messages(player: Any) -> List[str]:
    messages: List[str] = []
    for task in _player_task_status_list(player):
        error = _field(task, "error")
        message = _field(error, "message", default=error)
        if message:
            messages.append(str(message))
    return messages


def create_executed_yaml_result(options: Dict[str, Any]) -> Dict[str, Any]:
    """Build the result for a directly executed YAML file."""
    file_path = options["file"]
    player = options["player"]
    duration = options.get("duration", 0)
    has_player_error = _field(player, "status", default="done") == "error"
    has_failed_tasks = not _is_player_successful(player) and not has_player_error

    if has_player_error:
        success = False
        result_type = "failed"
    elif has_failed_tasks:
        success = False
        result_type = "partialFailed"
    else:
        success = True
        result_type = "success"

    output_path = _field(player, "output", "output_path")
    if output_path and not Path(output_path).exists():
        output_path = None

    error_message: Optional[str] = None
    setup_error = _field(player, "errorInSetup", "error_in_setup")
    if _field(setup_error, "message"):
        error_message = _field(setup_error, "message")
    elif has_player_error or has_failed_tasks:
        task_errors = _task_error_messages(player)
        if task_errors:
            error_message = "; ".join(task_errors)
        elif has_player_error:
            error_message = "Execution failed"
        else:
            error_message = "Some tasks failed"

    return {
        "file": file_path,
        "success": success,
        "executed": True,
        "output": output_path,
        "report": _field(player, "reportFile", "report_file") or None,
        "duration": duration,
        "resultType": result_type,
        "error": error_message,
    }


def create_unexpected_yaml_result(options: Dict[str, Any]) -> Dict[str, Any]:
    """Build the result for a file whose execution raised unexpectedly."""
    file_path = options["file"]
    error = options["error"]
    duration = options.get("duration", 0)
    player = options.get("player")
    output = _field(player, "output", "output_path") if player else None
    return {
        "file": file_path,
        "success": False,
        "executed": True,
        "output": output if output and Path(output).exists() else None,
        "report": (_field(player, "reportFile", "report_file") if player else None)
        or None,
        "duration": duration,
        "resultType": "failed",
        "error": _field(error, "message", default=str(error)),
    }


def resolve_yaml_max_attempts(retry: Optional[float] = None) -> int:
    """Total attempts for one file: retries + the initial run."""
    if (
        not isinstance(retry, (int, float))
        or isinstance(retry, bool)
        or retry != retry
        or retry in (float("inf"), float("-inf"))
        or retry < 1
    ):
        return 1
    return int(retry) + 1


def create_yaml_attempt(
    result: Dict[str, Any], attempt: int
) -> Dict[str, Any]:
    """Project one player result onto the per-attempt record."""
    return {
        "attempt": attempt,
        "success": result.get("success"),
        "output": result.get("output"),
        "report": result.get("report"),
        "error": result.get("error"),
        "duration": result.get("duration"),
        "resultType": result.get("resultType"),
    }


def get_yaml_attempts_duration(attempts: List[Dict[str, Any]]) -> int:
    """Aggregate duration across all attempts of one file."""
    return sum((attempt.get("duration") or 0) for attempt in attempts)


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


def get_results_by_type(
    results: List[Dict[str, Any]], result_type: str
) -> List[Dict[str, Any]]:
    return [r for r in results if r.get("resultType") == result_type]


def _get_results_by_type(
    results: List[Dict[str, Any]], result_type: str
) -> List[Dict[str, Any]]:
    return get_results_by_type(results, result_type)


def get_execution_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate counts for the batch execution summary."""
    return {
        "total": len(results),
        "successful": len(_get_results_by_type(results, "success")),
        "failed": len(_get_results_by_type(results, "failed")),
        "partialFailed": len(_get_results_by_type(results, "partialFailed")),
        "notExecuted": len(_get_results_by_type(results, "notExecuted")),
        "totalDuration": sum(r.get("duration") or 0 for r in results),
    }


def get_summary_absolute_path(summary: str) -> Path:
    return Path(get_midscene_run_dir("output")) / summary


def _to_output_relative_path(output_dir: Path, file_path: str) -> str:
    import os

    relative = os.path.relpath(str(file_path), str(output_dir))
    return relative if relative.startswith(".") else f"./{relative}"


def _relpath(file_path: str, base: Path) -> str:
    import os

    return os.path.relpath(str(file_path), str(base))


def _retry_attempt_report_path(report_file: str, attempt: int) -> Path:
    path = Path(report_file)
    if path.name == "index.html":
        return path.parent.parent / f"{path.parent.name}-attempt-{attempt}" / "index.html"
    return path.parent / f"{path.stem}-attempt-{attempt}{path.suffix}"


def preserve_yaml_attempt_report(attempt: Dict[str, Any]) -> Dict[str, Any]:
    """Move a completed attempt's report aside before the next retry reuses it."""
    source = attempt.get("report")
    if not source or not Path(source).exists():
        return attempt

    target = _retry_attempt_report_path(source, attempt["attempt"])
    source_path = Path(source)
    if source_path.name == "index.html":
        if target.parent.exists():
            shutil.rmtree(target.parent, ignore_errors=True)
        shutil.copytree(source_path.parent, target.parent)
        shutil.rmtree(source_path.parent, ignore_errors=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        source_path.unlink()

    return {**attempt, "report": str(target)}


def _safe_report_name_part(value: str) -> str:
    return re.sub(r'[:*?"<>|# ]', "-", value)


def _create_retry_report_name(file_path: str) -> str:
    name = Path(file_path).stem or "yaml"
    file_hash = hashlib.sha1(
        str(Path(file_path).resolve()).encode("utf-8")
    ).hexdigest()[:8]
    return f"{_safe_report_name_part(name)}-{file_hash}-retry-attempts"


def _to_test_status(attempt: Dict[str, Any]) -> str:
    if attempt.get("success"):
        return "passed"
    if attempt.get("resultType") == "notExecuted":
        return "skipped"
    return "failed"


def create_retry_attempt_report(result: Dict[str, Any]) -> Optional[str]:
    """Merge per-attempt reports into one retry report, if there are several."""
    attempts = [
        attempt
        for attempt in (result.get("attempts") or [])
        if attempt.get("report") and Path(attempt["report"]).exists()
    ]
    if len(attempts) <= 1:
        return None

    tags = []
    for index, attempt in enumerate(attempts):
        status = _to_test_status(attempt)
        title = (
            f"Attempt {attempt['attempt']}: {status} - "
            f"{Path(result['file']).name}"
        )
        attributes = [
            f'data-group-id="merged-group-{index}"',
            f'playwright_test_duration="{attempt.get("duration") or 0}"',
            f'playwright_test_status="{status}"',
            f'playwright_test_title="{quote(title, safe="")}"',
            f'playwright_test_id="{quote(_safe_report_name_part(Path(result["file"]).name) + "-attempt-" + str(attempt["attempt"]), safe="")}"',
            "is_merged=\"true\"",
        ]
        try:
            source_html = Path(attempt["report"]).read_text(encoding="utf-8")
        except OSError:
            source_html = ""
        match = _DUMP_SCRIPT_PATTERN.search(source_html)
        dump_content = match.group(1).strip() if match else ""
        tags.append(
            '<script type="midscene_web_dump" type="application/json" '
            f'{" ".join(attributes)}>\n{dump_content}\n</script>'
        )

    html = "<html><body>\n" + "\n".join(tags) + "\n</body></html>"
    output_dir = Path(get_midscene_run_dir("report"))
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{_create_retry_report_name(result['file'])}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def _warn_retry_report_failure(message: str) -> None:
    try:
        log_dir = Path(get_midscene_run_dir("log"))
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "execution-summary.log", "a", encoding="utf-8") as handle:
            handle.write(
                f"[{datetime.datetime.now().isoformat()}] {message}\n"
            )
    except Exception:
        # Summary output is more important than warning output.
        pass
    print("[Midscene]", message, file=sys.stderr)


def _create_retry_attempt_report_safely(
    result: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        return {"report": create_retry_attempt_report(result), "failed": False}
    except Exception as error:
        _warn_retry_report_failure(
            "Failed to merge retry attempt report for "
            f"{result.get('file')}: {error}"
        )
        return {"failed": True}


def _without_none(mapping: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in mapping.items() if value is not None}


def write_execution_summary_file(
    summary: Any, results: List[Dict[str, Any]]
) -> Optional[str]:
    """Write the JSON execution summary and any retry-attempt reports."""
    if not summary:
        return None

    index_path = get_summary_absolute_path(str(summary))
    output_dir = index_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    index_data: Dict[str, Any] = {
        "summary": {
            **get_execution_summary(results),
            "generatedAt": datetime.datetime.now().isoformat(),
        },
        "results": [],
    }

    for result in results:
        retry_report = _create_retry_attempt_report_safely(result)
        report = retry_report.get("report")
        if report is None and not retry_report.get("failed"):
            report = result.get("retryReport")

        item: Dict[str, Any] = {
            "script": _relpath(result["file"], output_dir),
            "success": result["success"],
            "resultType": result.get("resultType"),
        }
        if result.get("output"):
            item["output"] = _to_output_relative_path(
                output_dir, result["output"]
            )
        if result.get("report"):
            item["report"] = _relpath(result["report"], output_dir)
        if report:
            item["retryReport"] = _relpath(report, output_dir)
        if result.get("attempts") is not None:
            attempts = []
            for attempt in result["attempts"]:
                attempts.append(
                    _without_none(
                        {
                            "attempt": attempt.get("attempt"),
                            "success": attempt.get("success"),
                            "resultType": attempt.get("resultType"),
                            "output": (
                                _to_output_relative_path(
                                    output_dir, attempt["output"]
                                )
                                if attempt.get("output")
                                else None
                            ),
                            "report": (
                                _relpath(attempt["report"], output_dir)
                                if attempt.get("report")
                                else None
                            ),
                            "error": attempt.get("error"),
                            "duration": attempt.get("duration"),
                        }
                    )
                )
            item["attempts"] = attempts
        if result.get("error") is not None:
            item["error"] = result["error"]
        if result.get("duration") is not None:
            item["duration"] = result["duration"]

        index_data["results"].append(item)

    index_path.write_text(
        __import__("json").dumps(index_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Batch summary written to {index_path}")
    return str(index_path)


def print_execution_plan(config: Dict[str, Any]) -> None:
    """Print the batch execution plan (upstream printExecutionPlan)."""
    if config.get("setup"):
        print("   Setup script:")
        print(f"     - {config['setup']}")
    print("   Scripts:")
    for file in config.get("files") or []:
        print(f"     - {file}")
    print("📋 Execution plan")
    print(f"   Concurrency: {config.get('concurrent')}")
    print(f"   Keep window: {config.get('keepWindow', False)}")
    print(f"   Headed: {config.get('headed', False)}")
    print(f"   Continue on error: {config.get('continueOnError', False)}")
    print(f"   Retry: {config.get('retry') or 0}")
    print(f"   Share browser context: {config.get('shareBrowserContext', False)}")
    print(f"   Reuse browser page: {config.get('reusePage', False)}")
    print(f"   Summary output: {config.get('summary')}")


def print_execution_finished() -> None:
    """Print the closing marker of a batch run (upstream)."""
    print("Execution finished:")


def print_execution_summary(
    results: List[Dict[str, Any]], summary_path: str
) -> bool:
    """Print the batch execution summary and return whether it passed."""
    summary = get_execution_summary(results)
    successful_files = _get_results_by_type(results, "success")
    failed_files = _get_results_by_type(results, "failed")
    partial_failed_files = _get_results_by_type(results, "partialFailed")
    not_executed_files = _get_results_by_type(results, "notExecuted")
    success = (
        summary["failed"] == 0
        and summary["partialFailed"] == 0
        and summary["notExecuted"] == 0
    )

    print("\n📊 Execution Summary:")
    print(f"   Total files: {summary['total']}")
    print(f"   Successful: {summary['successful']}")
    print(f"   Failed: {summary['failed']}")
    print(f"   Partial failed: {summary['partialFailed']}")
    print(f"   Not executed: {summary['notExecuted']}")
    print(f"   Duration: {summary['totalDuration'] / 1000:.2f}s")
    print(f"   Summary: {summary_path}")

    if successful_files:
        print("\n✅ Successful files:")
        for result in successful_files:
            print(f"   {result['file']}")
            if result.get("report"):
                print(f"     Report: {result['report']}")
            if result.get("output"):
                print(f"     Output: {result['output']}")

    if failed_files:
        print("\n❌ Failed files")
        for result in failed_files:
            print(f"   {result['file']}")
            if result.get("error"):
                print(f"     Error: {result['error']}")

    if partial_failed_files:
        print("\n⚠️  Partial failed files (some tasks failed with continueOnError)")
        for result in partial_failed_files:
            print(f"   {result['file']}")
            if result.get("error"):
                print(f"     Error: {result['error']}")

    if not_executed_files:
        print("\n⏸️ Not executed files")
        for result in not_executed_files:
            print(f"   {result['file']}")

    if success:
        print("\n🎉 All files executed successfully!")
    else:
        print("\n⚠️ Some files failed or were not executed.")

    return success


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
