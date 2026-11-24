"""Synced from upstream packages/core/tests/unit-test/report-export.test.ts."""

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from midscene.core.dump.report_artifact_reader import (
    read_report_artifact_manifest,
    read_report_dump_scripts,
    read_report_runner_dump,
)
from midscene.core.dump.screenshot_store import ReportImageStore
from midscene.core.report import (
    ReportMergingTool,
    TestRunReportAssembler,
    write_report_html,
)
from midscene.core.report_cli import create_report_cli_commands
from midscene.core.report_generator import ReportGenerator
from midscene.core.screenshot_item import ScreenshotItem
from midscene.shared.report_artifact import export_report_artifact


def _fake_image_base64(size_bytes: int) -> str:
    return "data:image/png;base64," + "A" * size_bytes


async def _generator_source(tmp_path, mode: str) -> str:
    """A generator-backed report with two screenshots sharing image bytes."""
    path = tmp_path / mode / ("source.html" if mode == "inline" else "index.html")
    generator = ReportGenerator(
        report_path=str(path), screenshot_mode=mode, auto_print=False
    )
    generator.on_execution_update(
        {
            "id": "search",
            "logTime": 0,
            "name": "failed search",
            "tasks": [
                {
                    "taskId": f"task-{index}",
                    "type": "Insight",
                    "uiContext": {
                        "screenshot": ScreenshotItem.create(
                            _fake_image_base64(80), captured_at
                        )
                    },
                    "recorder": [],
                    "status": "finished",
                }
                for index, captured_at in enumerate((100, 200))
            ],
        },
        {
            "groupName": "test-group",
            "groupDescription": "test",
            "sdkVersion": "1.0.0-test",
            "modelBriefs": [],
        },
    )
    await generator.finalize()
    return str(path)


_MERGE_ATTRIBUTES = {
    "testId": "test",
    "testTitle": "test",
    "testStatus": "passed",
    "testDescription": "",
    "testDuration": 0,
}


def _fake_png(value: int) -> str:
    payload = bytes([value, value, value]) + b"\x00"
    return "data:image/png;base64," + base64.b64encode(payload).decode()


def _source(tmp_path) -> str:
    """A single-file report with two independent screenshots."""
    dump = {
        "groupName": "test-group",
        "executions": [
            {
                "id": "search",
                "name": "failed search",
                "tasks": [
                    {
                        "taskId": "task-0",
                        "type": "Insight",
                        "uiContext": {"screenshot": _fake_png(1)},
                    },
                    {
                        "taskId": "task-1",
                        "type": "Insight",
                        "uiContext": {"screenshot": _fake_png(2)},
                    },
                ],
            }
        ],
    }
    return write_report_html(dump, "source", str(tmp_path))


def _dump_script_count(path) -> int:
    return (
        Path(path)
        .read_text(encoding="utf-8")
        .count('<script id="midscene_report_dump"')
    )


def _group_dump_count(path) -> int:
    """Count merged group dumps written as ``midscene_web_dump`` scripts."""
    return (
        Path(path).read_text(encoding="utf-8").count('<script type="midscene_web_dump"')
    )


def test_export_preserves_the_source_through_same_name_cross_format_publication(
    tmp_path,
):
    original = _source(tmp_path)
    output_dir = tmp_path / "cross-format"
    inline = export_report_artifact(original, output_dir, "run")
    before = Path(inline).read_text(encoding="utf-8")

    external = export_report_artifact(
        inline,
        output_dir,
        "run",
        output_format="html-and-external-assets",
        overwrite=True,
    )
    assert Path(inline).read_text(encoding="utf-8") == before
    directory_before = (output_dir / "run" / "index.html").read_text(encoding="utf-8")

    restored = export_report_artifact(external, output_dir, "run", overwrite=True)
    assert restored == inline
    assert (output_dir / "run" / "index.html").read_text(
        encoding="utf-8"
    ) == directory_before
    assert _dump_script_count(restored) == 1


def _directory_source(tmp_path) -> str:
    """Export the fixture as an html-and-external-assets directory report."""
    inline = _source(tmp_path)
    return export_report_artifact(
        inline,
        tmp_path / "directory",
        "source",
        output_format="html-and-external-assets",
        overwrite=True,
    )


def test_merge_preserves_the_source_through_same_name_cross_format_publication(
    tmp_path,
):
    original = _source(tmp_path)
    output_dir = tmp_path / "cross-format"
    inline = export_report_artifact(original, output_dir, "run")
    before = Path(inline).read_text(encoding="utf-8")

    def publish(input_path, output_format):
        merger = ReportMergingTool()
        merger.append(
            {
                "reportFilePath": str(input_path),
                "reportAttributes": _MERGE_ATTRIBUTES,
            }
        )
        return merger.merge_reports(
            "run",
            {
                "outputDir": str(output_dir),
                "outputFormat": output_format,
                "overwrite": True,
            },
        )

    external = publish(inline, "html-and-external-assets")
    assert Path(inline).read_text(encoding="utf-8") == before
    directory_before = (output_dir / "run" / "report.json").read_text(encoding="utf-8")

    restored = publish(external, "single-html")
    assert restored == inline
    assert (output_dir / "run" / "report.json").read_text(
        encoding="utf-8"
    ) == directory_before
    assert _dump_script_count(restored) == 1


@pytest.mark.parametrize(
    "output_format",
    ["single-html", "html-and-external-assets"],
)
def test_allows_publication_beside_another_format_without_overwrite(
    tmp_path, output_format
):
    source = _source(tmp_path)
    output_dir = tmp_path / "siblings"
    output_dir.mkdir()
    sibling = (
        output_dir / "run"
        if output_format == "single-html"
        else output_dir / "run.html"
    )
    sentinel = sibling / "user-notes.txt" if output_format == "single-html" else sibling
    if output_format == "single-html":
        sibling.mkdir()
    sentinel.write_text("unrelated user data", encoding="utf-8")

    for overwrite in (False, True):
        output = export_report_artifact(
            source,
            output_dir,
            "run",
            output_format=output_format,
            overwrite=overwrite,
        )
        assert Path(output).exists() is True
        assert sentinel.read_text(encoding="utf-8") == "unrelated user data"


@pytest.mark.parametrize(
    "output_format",
    ["single-html", "html-and-external-assets"],
)
def test_rejects_one_of_two_concurrent_exports_without_replacing_the_winner(
    tmp_path, output_format
):
    source = _source(tmp_path)
    output_dir = tmp_path / "race"
    output_dir.mkdir()

    def export():
        return export_report_artifact(
            source,
            output_dir,
            "same",
            output_format=output_format,
            overwrite=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(export) for _ in range(2)]
        results = []
        for future in futures:
            try:
                results.append(("fulfilled", future.result()))
            except Exception as error:  # noqa: BLE001 - mirrors allSettled
                results.append(("rejected", error))

    fulfilled = [value for status, value in results if status == "fulfilled"]
    rejected = [value for status, value in results if status == "rejected"]
    assert len(fulfilled) == 1
    assert len(rejected) == 1
    assert _dump_script_count(fulfilled[0]) == 1
    assert any(entry.name.startswith(".") for entry in output_dir.iterdir()) is False


def _merge_repeated_source_once(input_path, tmp_path, directory: bool):
    merger = ReportMergingTool()
    for index in range(2):
        merger.append(
            {
                "reportFilePath": input_path,
                "reportAttributes": {
                    **_MERGE_ATTRIBUTES,
                    "testId": f"test-{index}",
                },
            }
        )
    output = merger.merge_reports(
        "merged",
        {
            "outputDir": str(tmp_path / "merged"),
            "rmOriginalReports": True,
        },
    )
    assert _group_dump_count(output) == 2
    assert Path(input_path).exists() is False
    if directory:
        assert Path(input_path).parent.exists() is False


def test_removes_a_repeated_inline_source_once_while_retaining_both_merged_groups(
    tmp_path,
):
    _merge_repeated_source_once(_source(tmp_path), tmp_path, directory=False)


def test_removes_a_repeated_directory_source_once_while_retaining_both_merged_groups(
    tmp_path,
):
    _merge_repeated_source_once(_directory_source(tmp_path), tmp_path, directory=True)


async def _assert_converts_to_both_formats(tmp_path, mode: str) -> None:
    input_path = await _generator_source(tmp_path, mode)
    (Path(input_path).parent / "unused-debug.json").write_text(
        '{"notPartOfReport":true}', encoding="utf-8"
    )

    for output_format in ("single-html", "html-and-external-assets"):
        exported = export_report_artifact(
            input_path,
            tmp_path / "out",
            output_format,
            output_format=output_format,
        )
        moved = tmp_path / f"moved-{output_format}"
        if output_format == "single-html":
            Path(exported).rename(moved)
            entry = moved
        else:
            Path(exported).parent.rename(moved)
            entry = moved / "index.html"

        dump = json.loads(read_report_dump_scripts(entry)[0]["content"])
        refs = [
            task["uiContext"]["screenshot"] for task in dump["executions"][0]["tasks"]
        ]
        assert [ref["capturedAt"] for ref in refs] == [100, 200]
        assert refs[0]["id"] != refs[1]["id"]
        images = ReportImageStore(
            mode=("inline" if output_format == "single-html" else "directory"),
            report_path=str(entry),
        )
        assert [images.load_data_uri(ref) for ref in refs] == [
            _fake_image_base64(80),
            _fake_image_base64(80),
        ]
        if output_format == "html-and-external-assets":
            assert refs[0]["path"] == refs[1]["path"]
            assert sorted(os.listdir(moved)) == [
                "data",
                "index.html",
                "report.json",
                "screenshots",
            ]
            assert len(os.listdir(moved / "screenshots")) == 1
            assert read_report_artifact_manifest(str(entry))["kind"] == "agent"
            assert "failed search" not in entry.read_text(encoding="utf-8")
        else:
            assert _fake_image_base64(80) in entry.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_converts_inline_input_to_either_format_and_retains_independent_observations_after_relocation(
    tmp_path,
):
    await _assert_converts_to_both_formats(tmp_path, "inline")


@pytest.mark.asyncio
async def test_converts_directory_input_to_either_format_and_retains_independent_observations_after_relocation(
    tmp_path,
):
    await _assert_converts_to_both_formats(tmp_path, "directory")


@pytest.mark.asyncio
async def test_preserves_test_runner_metadata_through_directory_and_single_file_exports(
    tmp_path,
):
    input_path = await _generator_source(tmp_path, "inline")
    runner = {
        "schemaVersion": 1,
        "kind": "test-runner",
        "runId": "test-export",
        "status": "failed",
        "startedAt": "1970-01-01T00:00:00.000Z",
        "endedAt": "1970-01-01T00:00:01.000Z",
        "durationMs": 1000,
        "summary": {
            "total": 1,
            "passed": 0,
            "failed": 1,
            "notRun": 0,
            "filtered": 0,
            "collectionErrors": 0,
            "documentFailures": 0,
            "projectFailures": 0,
        },
        "metrics": {
            "modelCallCount": 0,
            "modelTimeMs": 0,
            "promptTokens": 0,
            "cachedInputTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
        },
        "projects": [],
    }
    test_report = await TestRunReportAssembler().assemble_async(
        {
            "outputDir": str(tmp_path / "test"),
            "reportFileName": "run",
            "sources": [{"scopeId": "case", "sourcePath": input_path}],
            "buildRunnerDump": lambda _: runner,
        }
    )

    directory = export_report_artifact(
        test_report,
        tmp_path / "exports",
        "external",
        output_format="html-and-external-assets",
    )
    assert read_report_artifact_manifest(str(directory))["kind"] == "test"
    assert read_report_runner_dump(directory) == runner

    single = export_report_artifact(directory, tmp_path / "exports", "single")
    assert read_report_runner_dump(single) == runner
    assert len(read_report_dump_scripts(single)) == 1


@pytest.mark.asyncio
async def test_fails_before_publishing_when_an_image_dependency_is_missing_preserving_its_input_and_the_old_output(
    tmp_path,
):
    input_path = await _generator_source(tmp_path, "directory")
    ref = json.loads(read_report_dump_scripts(input_path)[0]["content"])["executions"][
        0
    ]["tasks"][0]["uiContext"]["screenshot"]
    Path(input_path).parent.joinpath(ref["path"]).unlink()

    out = tmp_path / "exports"
    out.mkdir()
    (out / "broken.html").write_text("previous output", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        export_report_artifact(input_path, out, "broken", overwrite=True)
    assert Path(input_path).exists()
    assert (out / "broken.html").read_text(encoding="utf-8") == ("previous output")
    assert sorted(os.listdir(out)) == ["broken.html"]

    with pytest.raises(FileNotFoundError):
        export_report_artifact(
            input_path,
            Path(input_path).parent,
            "directory",
            output_format="html-and-external-assets",
            overwrite=True,
        )
    assert (out / "broken.html").read_text(encoding="utf-8") == ("previous output")


@pytest.mark.asyncio
async def test_exports_via_the_report_tool_with_an_explicit_format_and_a_self_contained_default(
    tmp_path,
):
    input_path = await _generator_source(tmp_path, "directory")
    command = create_report_cli_commands()[0].definition
    await command.handler(
        {
            "action": "export",
            "htmlPath": input_path,
            "outputDir": str(tmp_path / "cli"),
            "outputName": "single",
        }
    )
    assert _fake_image_base64(80) in (tmp_path / "cli" / "single.html").read_text(
        encoding="utf-8"
    )
    await command.handler(
        {
            "action": "export",
            "htmlPath": input_path,
            "outputDir": str(tmp_path / "cli"),
            "outputName": "external",
            "outputFormat": "html-and-external-assets",
        }
    )
    assert (
        read_report_artifact_manifest(
            str(tmp_path / "cli" / "external" / "index.html")
        )["status"]
        == "complete"
    )
