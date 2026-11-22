"""Synced from upstream packages/cli/tests/unit-test/execution-summary.test.ts."""

import json
import re
from pathlib import Path

import pytest

from midscene.cli import execution_summary as summary_module
from midscene.cli.execution_summary import (
    create_executed_yaml_result,
    create_unexpected_yaml_result,
    create_yaml_attempt,
    get_results_by_type,
    get_yaml_attempts_duration,
    is_yaml_player_successful,
    not_executed_error,
    preserve_yaml_attempt_report,
    print_execution_finished,
    print_execution_plan,
    print_execution_summary,
    resolve_yaml_max_attempts,
    write_execution_summary_file,
)


def _write_fake_report(file_path: Path, group_name: str, execution_name: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    dump = (
        json.dumps(
            {
                "sdkVersion": "1.9.1",
                "groupName": group_name,
                "groupDescription": "",
                "modelBriefs": [],
                "executions": [
                    {"id": execution_name, "name": execution_name, "tasks": []}
                ],
            }
        )
    )
    file_path.write_text(
        "<html><body>"
        f'<script type="midscene_web_dump" data-group-id="{group_name}">'
        f"{dump}</script></body></html>",
        encoding="utf-8",
    )


def test_preserves_a_directory_based_report_as_a_complete_retry_artifact(tmp_path):
    """preserves a directory-based report as a complete retry artifact"""
    root = tmp_path
    report_file = root / "custom-report" / "index.html"
    screenshot_file = root / "custom-report" / "screenshots" / "1.png"
    screenshot_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("<html>attempt one</html>", encoding="utf-8")
    screenshot_file.write_text("screenshot", encoding="utf-8")

    preserved = preserve_yaml_attempt_report(
        {
            "attempt": 1,
            "success": False,
            "report": str(report_file),
            "duration": 10,
            "resultType": "failed",
        }
    )
    archived_report = root / "custom-report-attempt-1" / "index.html"

    assert preserved["report"] == str(archived_report)
    assert not report_file.exists()
    assert "attempt one" in archived_report.read_text(encoding="utf-8")
    assert (
        root / "custom-report-attempt-1" / "screenshots" / "1.png"
    ).read_text(encoding="utf-8") == "screenshot"


def test_prints_the_configured_retry_count_in_the_execution_plan(capsys):
    """prints the configured retry count in the execution plan"""
    print_execution_plan(
        {
            "files": ["/tmp/case.yaml"],
            "concurrent": 1,
            "continueOnError": False,
            "retry": 2,
            "summary": "summary.json",
            "shareBrowserContext": False,
            "headed": False,
            "keepWindow": False,
        }
    )

    assert "   Retry: 2" in capsys.readouterr().out


def test_prints_failed_file_error_details(capsys):
    """prints failed file error details"""
    results = [
        {
            "file": "/tmp/failed.yaml",
            "success": False,
            "executed": True,
            "duration": 12,
            "resultType": "failed",
            "error": "Assertion failed: expected page title",
        }
    ]

    success = print_execution_summary(results, "/tmp/summary.json")

    assert success is False
    assert "     Error: Assertion failed: expected page title" in capsys.readouterr().out


def test_prints_successful_file_report_and_output_details(capsys):
    """prints successful file report and output details"""
    results = [
        {
            "file": "/tmp/passed.yaml",
            "success": True,
            "executed": True,
            "duration": 12,
            "resultType": "success",
            "report": "/tmp/midscene_run/report/passed.html",
            "output": "/tmp/midscene_run/output/passed.json",
        }
    ]

    success = print_execution_summary(results, "/tmp/summary.json")

    assert success is True
    output = capsys.readouterr().out
    assert "   /tmp/passed.yaml" in output
    assert "     Report: /tmp/midscene_run/report/passed.html" in output
    assert "     Output: /tmp/midscene_run/output/passed.json" in output


def test_writes_a_retry_report_with_per_attempt_statuses(tmp_path, monkeypatch):
    """writes a retry report with per-attempt statuses"""
    root = tmp_path
    run_dir = root / "midscene-run"
    report_dir = run_dir / "report"
    yaml = root / "case.yaml"
    attempt_one_report = report_dir / "attempt-1.html"
    attempt_two_report = report_dir / "attempt-2.html"

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    yaml.write_text("web:\n  url: about:blank\ntasks: []\n", encoding="utf-8")
    _write_fake_report(attempt_one_report, "attempt-one", "failed-before-retry")
    _write_fake_report(attempt_two_report, "attempt-two", "passed-after-retry")

    summary_path = write_execution_summary_file(
        "summary.json",
        [
            {
                "file": str(yaml),
                "success": True,
                "executed": True,
                "report": str(attempt_two_report),
                "duration": 20,
                "resultType": "success",
                "attempts": [
                    {
                        "attempt": 1,
                        "success": False,
                        "report": str(attempt_one_report),
                        "error": "first attempt failed",
                        "duration": 10,
                        "resultType": "failed",
                    },
                    {
                        "attempt": 2,
                        "success": True,
                        "report": str(attempt_two_report),
                        "duration": 10,
                        "resultType": "success",
                    },
                ],
            }
        ],
    )

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    assert [
        {
            "attempt": attempt["attempt"],
            "success": attempt["success"],
            "resultType": attempt["resultType"],
        }
        for attempt in summary["results"][0]["attempts"]
    ] == [
        {"attempt": 1, "success": False, "resultType": "failed"},
        {"attempt": 2, "success": True, "resultType": "success"},
    ]
    assert re.fullmatch(
        r"\.\./report/case-[a-f0-9]{8}-retry-attempts\.html",
        summary["results"][0]["retryReport"],
    )

    retry_report_path = Path(summary_path).parent / summary["results"][0]["retryReport"]
    retry_report = retry_report_path.read_text(encoding="utf-8")
    assert 'playwright_test_status="failed"' in retry_report
    assert 'playwright_test_status="passed"' in retry_report
    assert "Attempt%201%3A%20failed%20-%20case.yaml" in retry_report
    assert "Attempt%202%3A%20passed%20-%20case.yaml" in retry_report


def test_writes_distinct_retry_reports_for_yaml_files_with_duplicate_basenames(
    tmp_path, monkeypatch
):
    """writes distinct retry reports for YAML files with duplicate basenames"""
    root = tmp_path
    run_dir = root / "midscene-run"
    report_dir = run_dir / "report"
    yaml_one = root / "flows" / "login" / "case.yaml"
    yaml_two = root / "checkout" / "case.yaml"

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    for name, group, execution in (
        ("login-attempt-1.html", "login-attempt-one", "login-failed-before-retry"),
        ("login-attempt-2.html", "login-attempt-two", "login-passed-after-retry"),
        ("checkout-attempt-1.html", "checkout-attempt-one", "checkout-failed-before-retry"),
        ("checkout-attempt-2.html", "checkout-attempt-two", "checkout-passed-after-retry"),
    ):
        _write_fake_report(report_dir / name, group, execution)

    def result(file_path, first_report, second_report):
        return {
            "file": str(file_path),
            "success": True,
            "executed": True,
            "report": str(second_report),
            "duration": 20,
            "resultType": "success",
            "attempts": [
                {
                    "attempt": 1,
                    "success": False,
                    "report": str(first_report),
                    "duration": 10,
                    "resultType": "failed",
                },
                {
                    "attempt": 2,
                    "success": True,
                    "report": str(second_report),
                    "duration": 10,
                    "resultType": "success",
                },
            ],
        }

    summary_path = write_execution_summary_file(
        "summary.json",
        [
            result(
                yaml_one,
                report_dir / "login-attempt-1.html",
                report_dir / "login-attempt-2.html",
            ),
            result(
                yaml_two,
                report_dir / "checkout-attempt-1.html",
                report_dir / "checkout-attempt-2.html",
            ),
        ],
    )

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    retry_reports = [item["retryReport"] for item in summary["results"]]

    assert len(retry_reports) == 2
    assert len(set(retry_reports)) == 2
    for retry_report in retry_reports:
        assert re.fullmatch(
            r"\.\./report/case-[a-f0-9]{8}-retry-attempts\.html", retry_report
        )
        assert (Path(summary_path).parent / retry_report).exists()


@pytest.mark.asyncio
async def test_keeps_writing_summary_when_retry_report_merging_fails(
    tmp_path, monkeypatch, capsys
):
    """keeps writing summary when retry report merging fails"""
    root = tmp_path
    run_dir = root / "midscene-run"
    report_dir = run_dir / "report"
    yaml = root / "case.yaml"
    attempt_one_report = report_dir / "attempt-1.html"
    attempt_two_report = report_dir / "attempt-2.html"

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(run_dir))
    yaml.write_text("web:\n  url: about:blank\ntasks: []\n", encoding="utf-8")
    _write_fake_report(attempt_one_report, "attempt-one", "failed-before-retry")
    _write_fake_report(attempt_two_report, "attempt-two", "failed-after-retry")

    merge_calls = []

    def failing_merge(result):
        merge_calls.append(result)
        raise RuntimeError("merge failed")

    monkeypatch.setattr(
        summary_module, "create_retry_attempt_report", failing_merge
    )

    summary_path = write_execution_summary_file(
        "summary.json",
        [
            {
                "file": str(yaml),
                "success": False,
                "executed": True,
                "report": str(attempt_two_report),
                "error": "final attempt failed",
                "duration": 20,
                "resultType": "failed",
                "attempts": [
                    {
                        "attempt": 1,
                        "success": False,
                        "report": str(attempt_one_report),
                        "error": "first attempt failed",
                        "duration": 10,
                        "resultType": "failed",
                    },
                    {
                        "attempt": 2,
                        "success": False,
                        "report": str(attempt_two_report),
                        "error": "final attempt failed",
                        "duration": 10,
                        "resultType": "failed",
                    },
                ],
            }
        ],
    )

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    assert "retryReport" not in summary["results"][0]
    assert [
        {
            "attempt": attempt["attempt"],
            "success": attempt["success"],
            "resultType": attempt["resultType"],
        }
        for attempt in summary["results"][0]["attempts"]
    ] == [
        {"attempt": 1, "success": False, "resultType": "failed"},
        {"attempt": 2, "success": False, "resultType": "failed"},
    ]
    err = capsys.readouterr().err
    assert "[Midscene]" in err
    assert "Failed to merge retry attempt report" in err
    assert merge_calls
    assert (run_dir / "log" / "execution-summary.log").exists()


def test_executed_result_reports_success_with_existing_output(tmp_path):
    output = tmp_path / "out.json"
    report = tmp_path / "report.html"
    output.write_text("{}", encoding="utf-8")
    report.write_text("<html></html>", encoding="utf-8")

    result = create_executed_yaml_result(
        {
            "file": "/tmp/case.yaml",
            "duration": 42,
            "player": {
                "status": "done",
                "taskStatusList": [{"status": "done"}],
                "output": str(output),
                "reportFile": str(report),
            },
        }
    )

    assert result == {
        "file": "/tmp/case.yaml",
        "success": True,
        "executed": True,
        "output": str(output),
        "report": str(report),
        "duration": 42,
        "resultType": "success",
        "error": None,
    }


def test_executed_result_reports_partial_failure_from_task_errors():
    result = create_executed_yaml_result(
        {
            "file": "/tmp/case.yaml",
            "duration": 10,
            "player": {
                "status": "done",
                "taskStatusList": [
                    {"status": "error", "error": {"message": "assertion failed"}},
                ],
            },
        }
    )

    assert result["success"] is False
    assert result["resultType"] == "partialFailed"
    assert result["error"] == "assertion failed"
    assert is_yaml_player_successful(
        {"status": "done", "taskStatusList": [{"status": "done"}]}
    )


def test_executed_result_reports_player_failure():
    result = create_executed_yaml_result(
        {
            "file": "/tmp/case.yaml",
            "duration": 0,
            "player": {
                "status": "error",
                "errorInSetup": {"message": "browser crashed"},
            },
        }
    )

    assert result["success"] is False
    assert result["resultType"] == "failed"
    assert result["error"] == "browser crashed"


def test_executed_result_drops_a_missing_output_file(tmp_path):
    result = create_executed_yaml_result(
        {
            "file": "/tmp/case.yaml",
            "duration": 0,
            "player": {
                "status": "done",
                "output": str(tmp_path / "missing.json"),
            },
        }
    )

    assert result["output"] is None


def test_unexpected_result_reports_the_error_message():
    result = create_unexpected_yaml_result(
        {
            "file": "/tmp/case.yaml",
            "error": RuntimeError("boom"),
            "duration": 7,
        }
    )

    assert result["success"] is False
    assert result["executed"] is True
    assert result["error"] == "boom"
    assert result["resultType"] == "failed"
    assert result["duration"] == 7


def test_attempt_helpers_and_result_type_filtering():
    first = create_yaml_attempt(
        {
            "success": False,
            "output": "/tmp/a.json",
            "report": "/tmp/a.html",
            "error": "nope",
            "duration": 5,
            "resultType": "failed",
        },
        1,
    )
    second = create_yaml_attempt(
        {"success": True, "duration": 8, "resultType": "success"}, 2
    )

    assert first["attempt"] == 1
    assert first["error"] == "nope"
    assert second["attempt"] == 2
    assert get_yaml_attempts_duration([first, second]) == 13
    assert get_yaml_attempts_duration([]) == 0
    assert get_results_by_type([first, second], "failed") == [first]


def test_resolve_yaml_max_attempts_falls_back_to_one():
    assert resolve_yaml_max_attempts() == 1
    assert resolve_yaml_max_attempts(0) == 1
    assert resolve_yaml_max_attempts(float("nan")) == 1
    assert resolve_yaml_max_attempts(float("inf")) == 1
    assert resolve_yaml_max_attempts(2) == 3
    assert resolve_yaml_max_attempts(2.9) == 3


def test_not_executed_error_and_finished_marker(capsys):
    from midscene.cli.execution_summary import create_not_executed_yaml_result

    result = create_not_executed_yaml_result("/tmp/case.yaml")
    assert result["error"] == not_executed_error
    assert result["resultType"] == "notExecuted"

    print_execution_finished()
    assert "Execution finished:" in capsys.readouterr().out
