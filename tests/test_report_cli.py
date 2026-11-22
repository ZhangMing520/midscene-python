"""Port of upstream packages/core/tests/unit-test/report-cli.test.ts.

Covers the split / to-markdown / merge entry points. The upstream fixtures are
built with ``ReportActionDump``; the Python port writes the same embedded
``midscene_report_dump`` script tag through ``write_report_html``.
"""

import json

from typer.testing import CliRunner

from midscene.cli.index import app
from midscene.core.report import write_report_html
from midscene.core.report_cli import merge_report_files, split_report_file
from midscene.core.report_markdown import report_file_to_markdown


def _execution(execution_id: str) -> dict:
    return {
        "id": execution_id,
        "name": f"execution-{execution_id}",
        "tasks": [
            {
                "type": "Insight",
                "subType": "Locate",
                "param": {"prompt": "find something"},
                "status": "finished",
            }
        ],
    }


def _write_report(directory, name: str, group_name: str, execution_id: str) -> str:
    dump = {
        "sdkVersion": "1.0.0-test",
        "groupName": group_name,
        "groupDescription": f"{group_name} description",
        "modelBriefs": [],
        "deviceType": "web",
        "executions": [_execution(execution_id)],
    }
    html_path = write_report_html(dump, name, str(directory))
    assert html_path
    return html_path


def test_runs_report_split_through_the_generic_report_command(tmp_path):
    report_path = _write_report(
        tmp_path, "input-report", "split-test", "exec-cli-1"
    )
    output_dir = tmp_path / "output"

    result = CliRunner().invoke(
        app,
        [
            "report-tool",
            "--action",
            "split",
            "--htmlPath",
            report_path,
            "--outputDir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    # Rich may wrap the console output; normalize the captured line breaks.
    output = result.output.replace("\n", "")
    assert "Report split completed." in output
    assert f"Output path: {output_dir}" in output

    first_dump = json.loads(
        (output_dir / "1.execution.json").read_text(encoding="utf-8")
    )
    assert first_dump["executions"][0]["id"] == "exec-cli-1"


def test_supports_split_via_the_sdk_api(tmp_path):
    report_path = _write_report(
        tmp_path, "input-report-sdk", "sdk-test", "exec-sdk-1"
    )
    output_dir = tmp_path / "output-sdk"

    result = split_report_file(report_path, str(output_dir))

    assert len(result["executionJsonFiles"]) == 1
    assert (output_dir / "1.execution.json").exists()


def test_supports_to_markdown_via_the_sdk_api(tmp_path):
    report_path = _write_report(
        tmp_path, "input-report-sdk-md", "sdk-markdown-test", "exec-sdk-md-1"
    )
    output_dir = tmp_path / "output-sdk-md"

    result = report_file_to_markdown(report_path, str(output_dir))

    assert len(result["markdownFiles"]) == 1
    assert (output_dir / "report.md").exists()


def test_merges_multiple_reports_via_the_sdk_api(tmp_path):
    report_a = _write_report(tmp_path, "merge-input-a", "group-A", "exec-A")
    report_b = _write_report(tmp_path, "merge-input-b", "group-B", "exec-B")
    output_dir = tmp_path / "merge-output-sdk"

    result = merge_report_files(
        [report_a, report_b], str(output_dir), "merged-sdk"
    )

    assert result["mergedReportPath"].startswith(str(output_dir))
    assert (output_dir / "merged-sdk.html").exists()

    merged = (output_dir / "merged-sdk.html").read_text(encoding="utf-8")
    # The Python port keeps the base dump header but merges every execution.
    assert "exec-A" in merged
    assert "exec-B" in merged
