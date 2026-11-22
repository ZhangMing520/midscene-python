"""Synced from upstream packages/core/tests/unit-test/report-export.test.ts.

Python ports the export/publication half of this upstream suite. Cases that
depend on ReportMergingTool, TestRunReportAssembler, directory report reading
via ReportImageStore, or the report-tool CLI are skipped with concrete reasons.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from midscene.core.report import write_report_html
from midscene.shared.report_artifact import export_report_artifact


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
                    {"taskId": "task-0", "type": "Insight", "uiContext": {"screenshot": _fake_png(1)}},
                    {"taskId": "task-1", "type": "Insight", "uiContext": {"screenshot": _fake_png(2)}},
                ],
            }
        ],
    }
    return write_report_html(dump, "source", str(tmp_path))


def _dump_script_count(path) -> int:
    return Path(path).read_text(encoding="utf-8").count(
        '<script id="midscene_report_dump"'
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
    directory_before = (output_dir / "run" / "index.html").read_text(
        encoding="utf-8"
    )

    restored = export_report_artifact(external, output_dir, "run", overwrite=True)
    assert restored == inline
    assert (output_dir / "run" / "index.html").read_text(
        encoding="utf-8"
    ) == directory_before
    assert _dump_script_count(restored) == 1


@pytest.mark.skip(
    reason="Python has no ReportMergingTool; mergeReportFiles cannot publish a "
    "directory artifact in the cross-format sense tested upstream"
)
@pytest.mark.asyncio
async def test_merge_preserves_the_source_through_same_name_cross_format_publication():
    pass


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
    sentinel = (
        sibling / "user-notes.txt"
        if output_format == "single-html"
        else sibling
    )
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


@pytest.mark.skip(
    reason="Python has no ReportMergingTool and does not remove source reports "
    "after merging"
)
@pytest.mark.asyncio
async def test_removes_a_repeated_inline_source_once_while_retaining_both_merged_groups():
    pass


@pytest.mark.skip(
    reason="Python has no ReportMergingTool and does not remove source reports "
    "after merging"
)
@pytest.mark.asyncio
async def test_removes_a_repeated_directory_source_once_while_retaining_both_merged_groups():
    pass


@pytest.mark.skip(
    reason="Python export keeps data-URI screenshots instead of "
    "midscene_screenshot_ref objects and does not deduplicate assets"
)
@pytest.mark.asyncio
async def test_converts_inline_input_to_either_format_and_retains_independent_observations_after_relocation():
    pass


@pytest.mark.skip(
    reason="Python export keeps data-URI screenshots instead of "
    "midscene_screenshot_ref objects and does not deduplicate assets"
)
@pytest.mark.asyncio
async def test_converts_directory_input_to_either_format_and_retains_independent_observations_after_relocation():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler or test-runner directory "
    "artifact writer"
)
@pytest.mark.asyncio
async def test_preserves_test_runner_metadata_through_directory_and_single_file_exports():
    pass


@pytest.mark.skip(
    reason="Python export tolerates unresolved file-backed image references "
    "instead of failing before publication"
)
@pytest.mark.asyncio
async def test_fails_before_publishing_when_an_image_dependency_is_missing_preserving_its_input_and_the_old_output():
    pass


@pytest.mark.skip(
    reason="Python has no report-tool CLI export command (createReportCliCommands)"
)
@pytest.mark.asyncio
async def test_exports_via_the_report_tool_with_an_explicit_format_and_a_self_contained_default():
    pass
