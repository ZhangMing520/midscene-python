"""Synced from upstream packages/core/tests/unit-test/report-artifact-reader.test.ts."""

import pytest

from midscene.core.report_cli import read_report_dump
from midscene.core.report_generator import ReportGenerator


@pytest.mark.asyncio
async def test_reads_all_inline_executions_retaining_latest_progress_and_skipping_viewer_script_strings(
    tmp_path,
):
    path = tmp_path / "report.html"
    generator = ReportGenerator(report_path=str(path), auto_print=False)
    first = {"id": "first", "name": "before update", "tasks": []}
    generator.on_execution_update(first, {"groupName": "test-group"})
    await generator.flush()

    first["name"] = "after update </script> 中文"
    generator.on_execution_update(first, {"groupName": "test-group"})
    generator.on_execution_update(
        {"id": "second", "name": "second", "tasks": []},
        {"groupName": "test-group"},
    )
    await generator.finalize()

    dump = read_report_dump(str(path))
    assert [{"id": item["id"], "name": item["name"]} for item in dump["executions"]] == [
        {"id": "first", "name": "after update </script> 中文"},
        {"id": "second", "name": "second"},
    ]
    assert path.read_text(encoding="utf-8").find("<!doctype html>") != -1


@pytest.mark.skip(
    reason="Python ReportGenerator only renders single-file HTML and does not "
    "implement screenshotMode='directory' (no ReportArtifactStore writer)"
)
@pytest.mark.asyncio
async def test_reads_all_directory_executions_retaining_latest_progress_and_skipping_viewer_script_strings():
    pass
