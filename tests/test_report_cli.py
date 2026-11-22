"""Port of upstream packages/core/tests/unit-test/report-cli.test.ts.

Covers the split / to-markdown / merge entry points. The upstream fixtures are
built with ``ReportActionDump``; the Python port writes the same embedded
``midscene_report_dump`` script tag through ``write_report_html``.
"""

import json

import pytest
from typer.testing import CliRunner

from midscene.cli.index import app
from midscene.core.report import write_report_html
from midscene.core.report_cli import (
    create_report_cli_commands,
    merge_report_files,
    split_report_file,
)
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


def test_exposes_report_tool_as_the_only_generic_report_command():
    """exposes report-tool as the only generic report command"""
    commands = create_report_cli_commands()

    assert len(commands) == 1
    assert commands[0].name == "report-tool"
    assert not hasattr(commands[0], "aliases")


@pytest.mark.asyncio
async def test_create_report_cli_commands_run_split(tmp_path):
    """runs report split through the generic report command"""
    report_path = _write_report(
        tmp_path, "input-report", "split-test", "exec-cli-1"
    )
    output_dir = tmp_path / "output-command"
    [command] = create_report_cli_commands()

    result = await command.definition.handler(
        {
            "htmlPath": report_path,
            "outputDir": str(output_dir),
            "action": "split",
        }
    )

    assert result["isError"] is False
    assert "Report split completed." in result["content"][0]["text"]
    assert f"Output path: {output_dir}" in result["content"][0]["text"]
    first_dump = json.loads(
        (output_dir / "1.execution.json").read_text(encoding="utf-8")
    )
    assert first_dump["executions"][0]["id"] == "exec-cli-1"


@pytest.mark.asyncio
async def test_create_report_cli_commands_validate_split_parameters(tmp_path):
    """throws CLI-specific validation errors for split action parameters"""
    [command] = create_report_cli_commands()

    with pytest.raises(ValueError, match="report-tool: --htmlPath is required"):
        await command.definition.handler(
            {"action": "split", "outputDir": str(tmp_path / "missing-html")}
        )

    with pytest.raises(ValueError, match="report-tool: --outputDir is required"):
        await command.definition.handler(
            {
                "action": "split",
                "htmlPath": str(tmp_path / "missing-output" / "index.html"),
            }
        )


@pytest.mark.asyncio
async def test_create_report_cli_commands_run_to_markdown(tmp_path):
    """runs to-markdown export through the generic report command"""
    report_path = _write_report(
        tmp_path, "input-report-md", "markdown-test", "exec-md-1"
    )
    output_dir = tmp_path / "output-md-command"
    [command] = create_report_cli_commands()

    result = await command.definition.handler(
        {
            "htmlPath": report_path,
            "outputDir": str(output_dir),
            "action": "to-markdown",
        }
    )

    assert result["isError"] is False
    assert "Markdown export completed." in result["content"][0]["text"]
    assert f"Output path: {output_dir}" in result["content"][0]["text"]
    assert (output_dir / "report.md").exists()


@pytest.mark.asyncio
async def test_create_report_cli_commands_uses_index_html_for_directories(
    tmp_path,
):
    """uses index.html when htmlPath points to a directory"""
    report_dir = tmp_path / "input-report-dir"
    report_dir.mkdir()
    report_path = _write_report(
        report_dir, "index", "split-dir-test", "exec-dir-1"
    )
    assert report_path.startswith(str(report_dir))
    output_dir = tmp_path / "output-dir-command"
    [command] = create_report_cli_commands()

    result = await command.definition.handler(
        {
            "htmlPath": str(report_dir),
            "outputDir": str(output_dir),
            "action": "split",
        }
    )

    assert result["isError"] is False
    assert (output_dir / "1.execution.json").exists()


@pytest.mark.asyncio
async def test_create_report_cli_commands_reject_unsupported_actions(tmp_path):
    """rejects unsupported action values before executing report logic"""
    [command] = create_report_cli_commands()

    with pytest.raises(
        ValueError,
        match='report-tool: unsupported --action value "invalid-action"',
    ):
        await command.definition.handler(
            {
                "action": "invalid-action",
                "htmlPath": str(tmp_path / "missing-report" / "index.html"),
                "outputDir": str(tmp_path / "unused-output"),
            }
        )


@pytest.mark.asyncio
async def test_create_report_cli_commands_run_merge(tmp_path):
    """runs the merge action through the generic report command"""
    report_a = _write_report(tmp_path, "merge-cli-a", "cli-group-A", "exec-A")
    report_b = _write_report(tmp_path, "merge-cli-b", "cli-group-B", "exec-B")
    output_dir = tmp_path / "merge-output-command"
    [command] = create_report_cli_commands()

    result = await command.definition.handler(
        {
            "action": "merge-html",
            "htmlReport": [report_a, report_b],
            "outputDir": str(output_dir),
            "outputName": "merged-cli",
        }
    )

    assert result["isError"] is False
    assert "Merged 2 report(s) into" in result["content"][0]["text"]
    assert (output_dir / "merged-cli.html").exists()


@pytest.mark.asyncio
async def test_create_report_cli_commands_require_html_report_for_merge(tmp_path):
    """throws when --htmlReport is missing for the merge action"""
    [command] = create_report_cli_commands()

    with pytest.raises(
        ValueError, match="report-tool: --htmlReport is required"
    ):
        await command.definition.handler(
            {"action": "merge-html", "outputDir": str(tmp_path / "merge-missing")}
        )
