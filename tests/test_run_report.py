"""Synced from upstream packages/core/tests/unit-test/test-run-report.test.ts.

Upstream exercises TestRunReportAssembler, which has no Python port: Python
exposes ``build_test_run_report_dump`` plus the publication helpers exported by
``midscene.shared.report_artifact``. Assembler-specific cases are skipped with
concrete reasons. Publication cases are covered through the Python export entry
point, which owns the same atomic sibling/format semantics.
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


def _source(tmp_path: Path) -> str:
    """A single-file Agent report used as the publication input."""
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
                    }
                ],
            }
        ],
    }
    return write_report_html(dump, "source", str(tmp_path))


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler or ReportImageStore-backed "
    "screenshot references; export keeps data URIs instead of selecting final "
    "image delivery"
)
def test_selects_final_image_delivery_independently_of_agent_source_storage():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler source-index builder that merges "
    "incremental Agent snapshots per scope"
)
def test_merges_incremental_snapshots_once_per_agent_and_scope_while_preserving_coverage():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler that reads valid, unreadable and "
    "malformed Agent sources into diagnostics"
)
def test_retains_valid_sources_and_diagnoses_unreadable_or_malformed_sources():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler that can publish a runner-dump-only "
    "standalone report"
)
def test_builds_a_custom_only_standalone_report():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler and publication does not emit "
    "per-source data-report-id/data-runner-scope-id attributes"
)
def test_indexes_agent_executions_and_emits_independent_report_attributes():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler that indexes one shared Agent "
    "source under multiple scopes while emitting the group once"
)
def test_indexes_a_shared_agent_source_under_multiple_scopes_and_emits_it_once():
    pass


@pytest.mark.skip(
    reason="Python has no prepareTestRunReportSources dedupe across native Agent "
    "reports and legacy snapshots"
)
def test_counts_stable_executions_once_across_native_reports_and_legacy_snapshots():
    pass


@pytest.mark.skip(
    reason="Python has no TestRunReportAssembler directory report reader and no "
    "ambiguous-execution detection across source reports in one scope"
)
def test_uses_directory_mode_and_rejects_ambiguous_executions_in_one_scope():
    pass


@pytest.mark.parametrize("mode", ["sync", pytest.param("async", marks=pytest.mark.skip(
    reason="Python report publication is synchronous; there is no assembleAsync"
))])
@pytest.mark.parametrize("output_format", ["single-html", "html-and-external-assets"])
def test_preserves_unrelated_sibling_files_when_sync_assembly_publishes_either_format(
    tmp_path, mode, output_format
):
    source = _source(tmp_path)
    output_dir = tmp_path / output_format
    output_dir.mkdir()
    sibling = (
        output_dir / "run"
        if output_format == "single-html"
        else output_dir / "run.html"
    )
    sentinel = (
        sibling / "user-notes.txt" if output_format == "single-html" else sibling
    )
    if output_format == "single-html":
        sibling.mkdir()
    sentinel.write_text("unrelated", encoding="utf-8")

    for overwrite in (False, True):
        output = export_report_artifact(
            source,
            output_dir,
            "run",
            output_format=output_format,
            overwrite=overwrite,
        )
        assert sentinel.read_text(encoding="utf-8") == "unrelated"
        assert Path(output).exists()


@pytest.mark.parametrize("output_format", ["single-html", "html-and-external-assets"])
def test_rejects_one_concurrent_asynchronous_assembly_for_each_output_format(
    tmp_path, output_format
):
    source = _source(tmp_path)
    output_dir = tmp_path / output_format
    output_dir.mkdir()

    def export():
        return export_report_artifact(
            source,
            output_dir,
            "run",
            output_format=output_format,
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
    assert Path(fulfilled[0]).exists()


def test_preserves_the_sibling_artifact_when_overwrite_switches_output_modes(tmp_path):
    source = _source(tmp_path)
    output_dir = tmp_path / "output"
    standalone = export_report_artifact(source, output_dir, "mode-switch")
    assert Path(standalone).exists()

    directory = export_report_artifact(
        source,
        output_dir,
        "mode-switch",
        output_format="html-and-external-assets",
        overwrite=True,
    )
    assert Path(standalone).exists()
    assert Path(directory).exists()

    restored = export_report_artifact(
        source, output_dir, "mode-switch", overwrite=True
    )
    assert (output_dir / "mode-switch").exists()
    assert Path(restored).exists()
