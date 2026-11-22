"""Synced from upstream packages/core/tests/unit-test/report-artifact-reader.test.ts."""

import json

import pytest

from midscene.core.dump.html_utils import (
    generate_dump_script_tag,
    generate_report_artifact_script_tag,
)
from midscene.core.dump.report_artifact_reader import (
    read_report_action_dump,
    read_report_artifact_manifest_async,
)
from midscene.core.dump.report_artifact_store import ReportArtifactStore


def _dump(name: str, execution_id: str = "first") -> dict:
    return {
        "sdkVersion": "1.0.0-test",
        "groupName": "test-group",
        "modelBriefs": [],
        "executions": [{"id": execution_id, "name": name, "tasks": []}],
    }


def _script(dump: dict) -> str:
    return generate_dump_script_tag(
        json.dumps(dump, ensure_ascii=False), {"data-group-id": "test-group"}
    )


@pytest.mark.asyncio
async def test_reads_all_inline_executions_retaining_latest_progress_and_skipping_viewer_script_strings(
    tmp_path,
):
    """reads all inline executions, retaining latest progress and skipping Viewer script strings"""
    path = tmp_path / "report.html"
    html = "<!doctype html><html><body>"
    html += _script(_dump("before update"))
    html += _script(_dump("after update </script> 中文"))
    html += _script(_dump("second", "second"))
    html += "</body></html>"
    path.write_text(html, encoding="utf-8")

    dump = read_report_action_dump(path)
    assert [
        {"id": item["id"], "name": item["name"]} for item in dump["executions"]
    ] == [
        {"id": "first", "name": "after update </script> 中文"},
        {"id": "second", "name": "second"},
    ]
    assert (
        await read_report_artifact_manifest_async(path)
    ) is None
    assert path.read_text(encoding="utf-8").find("<!doctype html>") != -1


@pytest.mark.asyncio
async def test_reads_all_directory_executions_retaining_latest_progress_and_skipping_viewer_script_strings(
    tmp_path,
):
    """reads all directory executions, retaining latest progress and skipping Viewer script strings"""
    path = tmp_path / "index.html"
    store = ReportArtifactStore(tmp_path, "artifact-reader", "agent")
    store.write_execution(
        "first", _dump("before update"), {"groupName": "test-group"}
    )
    store.write_execution(
        "first", _dump("after update </script> 中文"), {"groupName": "test-group"}
    )
    store.write_execution(
        "second", _dump("second", "second"), {"groupName": "test-group"}
    )
    store.finalize()
    path.write_text(
        "<!doctype html><html><body>"
        + generate_report_artifact_script_tag("report.json")
        + "</body></html>",
        encoding="utf-8",
    )

    dump = read_report_action_dump(path)
    assert [
        {"id": item["id"], "name": item["name"]} for item in dump["executions"]
    ] == [
        {"id": "first", "name": "after update </script> 中文"},
        {"id": "second", "name": "second"},
    ]
    assert (
        await read_report_artifact_manifest_async(path)
    ) is not None
    assert path.read_text(encoding="utf-8").find("<!doctype html>") != -1
