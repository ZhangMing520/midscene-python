"""Synced from two upstream suites that share the same file name.

- packages/core/tests/unit-test/report-artifact.test.ts
- packages/shared/tests/unit-test/report-artifact.test.ts

The core suite records ScreenshotItem snapshots/frames and forks TypeScript
publisher child processes; those cases are skipped below. The Python store is
synchronous, so the "concurrent" cases call it sequentially while keeping the
upstream assertions unchanged.
"""

import json

import pytest

from midscene.core.dump.execution_recorder import ExecutionRecorder
from midscene.shared.report_artifact import (
    REPORT_ARTIFACT_SCHEMA_VERSION,
    ReportArtifactError,
    ReportArtifactStore,
    assert_report_artifact_path,
    parse_report_artifact_manifest,
    with_report_artifact_lock,
)


def _execution(execution_id, name="test-execution"):
    return {"id": execution_id, "name": name, "tasks": []}


# ---------------------------------------------------------------------------
# packages/core/tests/unit-test/report-artifact.test.ts
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Python ExecutionRecorder exposes no capture()/reference-image API "
    "and ExecutionDump has no referenceImageUrls constructor option"
)
def test_freezes_selected_executions_recorded_frames_errors_and_reference_images_before_persistence():
    """freezes selected executions, recorded frames, errors and reference images before persistence"""
    pass


def test_stores_the_latest_progress_by_id_and_keeps_anonymous_observations_separate():
    """stores the latest progress by ID and keeps anonymous observations separate"""
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
    """releases the lock when publication fails and retains the previous manifest"""
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
    """times out without stealing an active publisher lock or running a second transaction"""
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
    """serializes concurrent progress, indexes one file per execution and needs no Viewer"""
    store = ReportArtifactStore(tmp_path, "stream")
    # The Python store is synchronous; sequential calls keep the same semantics
    # as the upstream Promise.all of three progress writes.
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
    """preserves concurrent reused streams and rejects invalid report IDs"""
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
    """retains the existing group and all eight process publishers, including later original-writer updates"""
    pass


# ---------------------------------------------------------------------------
# packages/shared/tests/unit-test/report-artifact.test.ts
# ---------------------------------------------------------------------------


def test_exposes_the_schema_version_supported_by_the_manifest_contract():
    """exposes the schema version supported by the manifest contract"""
    assert REPORT_ARTIFACT_SCHEMA_VERSION == 1


def _manifest():
    return {
        "schemaVersion": 1,
        "kind": "agent",
        "status": "complete",
        "reportId": "run-1",
        "entry": "index.html",
        "groups": [
            {
                "id": "agent-1",
                "status": "complete",
                "attributes": {"title": "登录验证", "duration": 123},
                "dumps": ["data/run-1/1.json"],
            }
        ],
    }


def test_requires_stream_state_and_consistent_aggregate_completion():
    """requires stream state and consistent aggregate completion"""
    for status in (None, "failed", "running"):
        candidate = _manifest()
        group = dict(candidate["groups"][0])
        if status is None:
            del group["status"]
        else:
            group["status"] = status
        candidate["groups"] = [group]
        with pytest.raises(ReportArtifactError, match="Invalid"):
            parse_report_artifact_manifest(candidate)
    candidate = _manifest()
    candidate["status"] = "running"
    candidate["groups"] = [{**candidate["groups"][0], "status": "running"}]
    assert parse_report_artifact_manifest(candidate)["status"] == "running"


def test_accepts_portable_agent_and_test_metadata():
    """accepts portable Agent and Test metadata"""
    assert parse_report_artifact_manifest(_manifest()) == _manifest()
    candidate = _manifest()
    candidate["kind"] = "test"
    candidate["runner"] = "data/run-1/runner.json"
    assert parse_report_artifact_manifest(candidate)["kind"] == "test"


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/absolute",
        "https://host/file",
        "data/../secret",
        "data/%2e%2e/secret",
        "data\\secret",
        "data/file.json?token=secret",
    ],
)
def test_rejects_a_reference_outside_the_artifact(path):
    """rejects a reference outside the artifact: %s"""
    with pytest.raises(ReportArtifactError, match="Invalid report artifact path"):
        assert_report_artifact_path(path)


def test_rejects_unsupported_schemas_malformed_attributes_and_ambiguous_groups():
    """rejects unsupported schemas, malformed attributes and ambiguous groups"""
    candidate = _manifest()
    candidate["schemaVersion"] = 99
    with pytest.raises(ReportArtifactError, match="unsupported"):
        parse_report_artifact_manifest(candidate)

    candidate = _manifest()
    candidate["groups"] = [{**candidate["groups"][0], "attributes": {"title": {}}}]
    with pytest.raises(ReportArtifactError, match="Invalid"):
        parse_report_artifact_manifest(candidate)

    candidate = _manifest()
    candidate["groups"] = [candidate["groups"][0], candidate["groups"][0]]
    with pytest.raises(ReportArtifactError, match="Invalid"):
        parse_report_artifact_manifest(candidate)


def test_publish_report_artifact_sync_moves_files_and_respects_overwrite(tmp_path):
    from midscene.core.dump.report_artifact_publication import (
        publish_report_artifact_sync,
    )

    prepared = tmp_path / "prepared.json"
    prepared.write_text('{"ok": true}', encoding="utf-8")
    destination = tmp_path / "published.json"

    publish_report_artifact_sync(prepared, destination, False)
    assert destination.read_text(encoding="utf-8") == '{"ok": true}'
    # Non-overwrite file publication hard-links, so the prepared file remains.
    assert prepared.exists()

    prepared_again = tmp_path / "prepared-again.json"
    prepared_again.write_text('{"ok": false}', encoding="utf-8")
    with pytest.raises(ReportArtifactError, match="already exists"):
        publish_report_artifact_sync(prepared_again, destination, False)
    assert prepared_again.exists()

    publish_report_artifact_sync(prepared_again, destination, False, True)
    assert destination.read_text(encoding="utf-8") == '{"ok": false}'
    assert not prepared_again.exists()


def test_publish_report_artifact_sync_replaces_directories_when_overwriting(tmp_path):
    from midscene.core.dump.report_artifact_publication import (
        publish_report_artifact_sync,
    )

    prepared = tmp_path / "prepared-dir"
    prepared.mkdir()
    (prepared / "index.html").write_text("new", encoding="utf-8")
    destination = tmp_path / "report-dir"
    destination.mkdir()
    (destination / "old.html").write_text("old", encoding="utf-8")

    publish_report_artifact_sync(prepared, destination, True, True)

    assert sorted(path.name for path in destination.iterdir()) == ["index.html"]
    assert (destination / "index.html").read_text(encoding="utf-8") == "new"
