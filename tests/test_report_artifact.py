"""Tests for the directory report artifact store (no browser or model)."""

import json

import pytest

from midscene.core.report_artifact import (
    ReportArtifactError,
    ReportArtifactStore,
    publish_report_artifact,
    read_report_artifact,
    validate_manifest,
)


def _dump(name="run-1"):
    return {"groupName": "G", "executions": [{"name": name, "tasks": []}]}


class TestReportArtifactStore:
    def test_writes_manifest_and_execution_file(self, tmp_path):
        store = ReportArtifactStore(tmp_path, "demo-report")
        relative = store.write_execution("run-1", _dump(), {"tag": "web"})
        store.finalize()

        assert relative == "data/demo-report/1.json"
        assert (tmp_path / relative).exists()
        manifest = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert manifest["schemaVersion"] == 1
        assert manifest["kind"] == "agent"
        assert manifest["status"] == "complete"
        assert manifest["entry"] == "index.html"
        assert manifest["groups"][0]["dumps"] == [relative]
        assert manifest["groups"][0]["attributes"] == {"tag": "web"}

    def test_same_key_overwrites_in_place(self, tmp_path):
        store = ReportArtifactStore(tmp_path, "demo")
        first = store.write_execution("run-1", _dump())
        second = store.write_execution("run-1", _dump("updated"))

        assert first == second
        assert len(json.loads((tmp_path / "report.json").read_text())["groups"][0]["dumps"]) == 1
        stored = json.loads((tmp_path / second).read_text())
        assert stored["executions"][0]["name"] == "updated"

    def test_reuse_existing_report_merges_groups(self, tmp_path):
        first = ReportArtifactStore(tmp_path, "first")
        first.write_execution("a", _dump())
        first.finalize()

        second = ReportArtifactStore(tmp_path, "second", reuse_existing_report=True)
        second.write_execution("b", _dump())
        second.finalize()

        manifest = json.loads((tmp_path / "report.json").read_text())
        assert {group["id"] for group in manifest["groups"]} == {"first", "second"}
        assert manifest["status"] == "complete"

    def test_write_after_finalize_is_rejected(self, tmp_path):
        store = ReportArtifactStore(tmp_path, "demo")
        store.write_execution("a", _dump())
        store.finalize()

        with pytest.raises(ReportArtifactError, match="finalized"):
            store.write_execution("b", _dump())

    def test_rejects_invalid_report_id(self, tmp_path):
        with pytest.raises(ReportArtifactError, match="Invalid report artifact ID"):
            ReportArtifactStore(tmp_path, "bad id!")

    def test_runner_summary_is_stored_and_read_back(self, tmp_path):
        store = ReportArtifactStore(tmp_path, "demo", kind="test")
        store.write_execution("a", _dump())
        runner_path = store.write_runner({"files": 1, "status": "success"})
        store.finalize()

        artifact = read_report_artifact(tmp_path)
        assert artifact["manifest"]["runner"] == runner_path
        assert artifact["runner"] == {"files": 1, "status": "success"}
        assert artifact["executions"][0]["dump"]["groupName"] == "G"

    def test_rejects_unknown_kind(self, tmp_path):
        with pytest.raises(ReportArtifactError, match="kind"):
            ReportArtifactStore(tmp_path, "demo", kind="unknown")


class TestManifestValidation:
    def test_requires_a_complete_shape(self):
        with pytest.raises(ReportArtifactError):
            validate_manifest({"schemaVersion": 1})
        with pytest.raises(ReportArtifactError, match="schemaVersion"):
            validate_manifest(
                {"schemaVersion": 2, "kind": "agent", "status": "running", "reportId": "r", "entry": "index.html", "groups": []}
            )


class TestPublication:
    def test_moves_the_directory_and_refuses_to_overwrite(self, tmp_path):
        prepared = tmp_path / "prepared"
        prepared.mkdir()
        (prepared / "report.json").write_text("{}", encoding="utf-8")
        destination = tmp_path / "final"

        publish_report_artifact(prepared, destination)
        assert (destination / "report.json").exists()
        assert not prepared.exists()

        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(ReportArtifactError, match="already exists"):
            publish_report_artifact(other, destination)

        publish_report_artifact(other, destination, overwrite=True)
        assert (destination / "report.json").exists() is False