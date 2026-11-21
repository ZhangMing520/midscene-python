"""Tests for the directory report artifact store (no browser or model)."""

import json

import pytest

from midscene.core.report_artifact import (
    ReportArtifactError,
    ReportArtifactStore,
    export_report_artifact,
    publish_report_artifact,
    read_report_artifact,
    validate_manifest,
)

_PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _dump(name="run-1"):
    return {"groupName": "G", "executions": [{"name": name, "tasks": []}]}


def _dump_with_image(name="run-1"):
    return {
        "groupName": "G",
        "executions": [
            {
                "name": name,
                "tasks": [
                    {
                        "type": "Insight",
                        "uiContext": {
                            "screenshot": f"data:image/png;base64,{_PNG_1PX}"
                        },
                    }
                ],
            }
        ],
    }


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


class TestExportReportArtifact:
    def _make_artifact(self, root):
        store = ReportArtifactStore(root, "demo-report")
        store.write_execution("run-1", _dump_with_image())
        store.finalize()
        return root

    def test_exports_directory_artifact_as_single_html(self, tmp_path):
        from midscene.core.report_viewer import read_report_dump

        source = self._make_artifact(tmp_path / "report")
        output = tmp_path / "out"
        path = export_report_artifact(source, output, "exported")

        assert path == str(output / "exported.html")
        assert (output / "exported.html").exists()
        dump = read_report_dump(path)
        assert dump["groupName"] == "G"
        assert dump["executions"][0]["name"] == "run-1"

    def test_exports_html_with_external_assets(self, tmp_path):
        source = self._make_artifact(tmp_path / "report")
        output = tmp_path / "out"
        path = export_report_artifact(
            source, output, "bundle", output_format="html-and-external-assets"
        )

        artifact = output / "bundle"
        assert path == str(artifact / "index.html")
        screenshots = list((artifact / "screenshots").glob("*.png"))
        assert len(screenshots) == 1
        assert screenshots[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        html = (artifact / "index.html").read_text(encoding="utf-8")
        assert '"storage": "file"' in html

    def test_refuses_to_overwrite_unless_requested(self, tmp_path):
        source = self._make_artifact(tmp_path / "report")
        output = tmp_path / "out"
        export_report_artifact(source, output, "exported")

        with pytest.raises(ReportArtifactError, match="already exists"):
            export_report_artifact(source, output, "exported")
        assert export_report_artifact(source, output, "exported", overwrite=True)

    def test_rejects_destination_equal_to_input(self, tmp_path):
        from midscene.core.report_viewer import write_report_html

        source = write_report_html(_dump(), "orig", str(tmp_path))
        with pytest.raises(ReportArtifactError, match="must differ"):
            export_report_artifact(source, tmp_path, "orig")

    def test_rejects_missing_input(self, tmp_path):
        with pytest.raises(ReportArtifactError):
            export_report_artifact(tmp_path / "missing", tmp_path / "out", "x")

    def test_rejects_invalid_export_name(self, tmp_path):
        source = self._make_artifact(tmp_path / "report")
        for name in ("report.html", "a/b", ".."):
            with pytest.raises(ReportArtifactError, match="reportFileName"):
                export_report_artifact(source, tmp_path / "out", name)

    def test_reads_single_file_html_input(self, tmp_path):
        from midscene.core.report_viewer import write_report_html

        source = write_report_html(_dump("single"), "single", str(tmp_path))
        path = export_report_artifact(source, tmp_path / "out", "copy")

        assert (tmp_path / "out" / "copy.html").exists()
        assert path.endswith("copy.html")

    def test_reexports_external_bundle_as_single_html(self, tmp_path):
        from midscene.core.report_viewer import read_report_dump

        source = self._make_artifact(tmp_path / "report")
        bundle = export_report_artifact(
            source, tmp_path / "out", "bundle", output_format="html-and-external-assets"
        )
        path = export_report_artifact(bundle, tmp_path / "single", "resingle")

        dump = read_report_dump(path)
        screenshot = dump["executions"][0]["tasks"][0]["uiContext"]["screenshot"]
        # The standalone file must embed the image; a relative screenshot path
        # cannot resolve next to the exported HTML.
        assert screenshot.startswith("data:image/png;base64,")
        assert (tmp_path / "single" / "screenshots").exists() is False

    def test_reexports_external_bundle_with_its_own_screenshots(self, tmp_path):
        source = self._make_artifact(tmp_path / "report")
        bundle = export_report_artifact(
            source, tmp_path / "out", "bundle", output_format="html-and-external-assets"
        )
        path = export_report_artifact(
            bundle, tmp_path / "out2", "bundle2", output_format="html-and-external-assets"
        )

        artifact = tmp_path / "out2" / "bundle2"
        assert path == str(artifact / "index.html")
        screenshot = next((artifact / "screenshots").glob("*.png"))
        assert screenshot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert './screenshots/' in (artifact / "index.html").read_text(encoding="utf-8")
