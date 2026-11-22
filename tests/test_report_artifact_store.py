"""Synced from upstream packages/core/tests/unit-test/report-artifact.test.ts.

The upstream suite forks TypeScript publisher processes and records
ScreenshotItem/reference-image snapshots; those cases are skipped below. The
Python store is synchronous, so the "concurrent" cases call it sequentially
(the upstream assertions are kept unchanged).
"""

import json

import pytest

from midscene.core.dump.execution_recorder import ExecutionRecorder
from midscene.shared.report_artifact import (
    ReportArtifactError,
    ReportArtifactStore,
    with_report_artifact_lock,
)


def _execution(execution_id, name="test-execution"):
    return {"id": execution_id, "name": name, "tasks": []}


@pytest.mark.skip(
    reason="Python ExecutionRecorder exposes no capture()/reference-image API; "
    "it only keeps the latest execution state"
)
def test_freezes_selected_executions_recorded_frames_errors_and_reference_images_before_persistence():
    pass


def test_stores_the_latest_progress_by_id_and_keeps_anonymous_observations_separate():
    recorder = ExecutionRecorder()
    recorder.record(_execution("stable", "first"))
    recorder.record(_execution("stable", "latest"))
    for _ in range(2):
        recorder.record({"logTime": 100, "name": "anonymous", "tasks": []})

    assert [execution["name"] for execution in recorder.executions] == [
        "latest",
        "anonymous",
        "anonymous",
    ]


def test_releases_the_lock_when_publication_fails_and_retains_the_previous_manifest(
    tmp_path,
):
    (tmp_path / "report.json").write_text("invalid manifest", encoding="utf-8")
    store = ReportArtifactStore(tmp_path, "failed", "agent", True)

    with pytest.raises(ReportArtifactError):
        store.write_execution("step", "{}", {})

    assert (tmp_path / "report.json").read_text(encoding="utf-8") == (
        "invalid manifest"
    )
    assert (tmp_path / ".report.json.lock").exists() is False

    fresh = ReportArtifactStore(tmp_path, "fresh")
    fresh.write_execution("step", "{}", {})
    fresh.finalize()
    manifest = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert manifest["groups"][0]["id"] == "fresh"


def test_times_out_without_stealing_an_active_publisher_lock_or_running_a_second_transaction(
    tmp_path,
):
    second_publication = []

    def publish_inside_lock():
        with pytest.raises(
            ReportArtifactError,
            match="Timed out waiting for report artifact lock",
        ):
            with_report_artifact_lock(
                tmp_path, lambda: second_publication.append(True), 25
            )
        assert (tmp_path / ".report.json.lock").exists() is True
        assert second_publication == []

    with_report_artifact_lock(tmp_path, publish_inside_lock)
    assert (tmp_path / ".report.json.lock").exists() is False

    with_report_artifact_lock(tmp_path, lambda: second_publication.append(True))
    assert second_publication == [True]


def test_serializes_concurrent_progress_indexes_one_file_per_execution_and_needs_no_viewer(
    tmp_path,
):
    store = ReportArtifactStore(tmp_path, "stream")
    store.write_execution("step", {"state": "running"}, {})
    store.write_execution("step", {"state": "finished"}, {})
    store.write_execution("other", {"state": "failed"}, {})
    store.write_runner({"cases": []})
    store.finalize()

    manifest = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"

    with pytest.raises(ReportArtifactError, match="finalized"):
        store.write_execution("late", "{}", {})
    with pytest.raises(ReportArtifactError, match="finalized"):
        store.write_runner("{}")

    assert len(manifest["groups"][0]["dumps"]) == 2
    first_dump = json.loads(
        (tmp_path / manifest["groups"][0]["dumps"][0]).read_text(encoding="utf-8")
    )
    assert first_dump == {"state": "finished"}
    assert (tmp_path / "index.html").exists() is False
    assert sorted(name for name in (tmp_path / "data" / "stream").iterdir()) == [
        tmp_path / "data" / "stream" / "1.json",
        tmp_path / "data" / "stream" / "2.json",
        tmp_path / "data" / "stream" / "runner.json",
    ]


def test_preserves_concurrent_reused_streams_and_rejects_invalid_report_ids(
    tmp_path,
):
    stores = [
        ReportArtifactStore(tmp_path, report_id, "agent", True)
        for report_id in ("first", "second")
    ]
    for store in stores:
        store.write_execution("step", "{}", {})

    manifest = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert sorted(group["id"] for group in manifest["groups"]) == [
        "first",
        "second",
    ]
    with pytest.raises(ReportArtifactError, match="Invalid report artifact ID"):
        ReportArtifactStore(tmp_path, "../outside")


@pytest.mark.skip(
    reason="upstream forks eight TypeScript publisher child processes; the "
    "Python port has no equivalent subprocess publisher"
)
def test_retains_the_existing_group_and_all_eight_process_publishers_including_later_original_writer_updates():
    pass
