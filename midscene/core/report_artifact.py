"""Directory report artifacts (upstream dump/report-artifact-*.ts, PR1 #3312).

A directory report is a folder instead of a single HTML file:

    <root>/report.json            manifest: kind, status, groups, dumps
    <root>/data/<reportId>/1.json one execution dump per file
    <root>/data/<reportId>/runner.json optional test-run summary

Every write is atomic (temp file + rename) and the manifest is only replaced
while holding a lock file, so a reader never sees a truncated artifact and two
publishers never clobber each other.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

SCHEMA_VERSION = 1
REPORT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
ARTIFACT_KINDS = ("agent", "test")
ARTIFACT_STATUSES = ("running", "complete")


class ReportArtifactError(ValueError):
    """Raised for an invalid or inconsistent report artifact."""


def validate_report_id(report_id: str) -> str:
    if not isinstance(report_id, str) or not REPORT_ID_PATTERN.match(report_id):
        raise ReportArtifactError("Invalid report artifact ID")
    return report_id


def validate_manifest(manifest: Any) -> Dict[str, Any]:
    """Check the manifest shape before it is written or trusted."""
    if not isinstance(manifest, dict):
        raise ReportArtifactError("Report manifest must be an object")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ReportArtifactError("Unsupported report manifest schemaVersion")
    if manifest.get("kind") not in ARTIFACT_KINDS:
        raise ReportArtifactError("Report manifest kind must be agent or test")
    if manifest.get("status") not in ARTIFACT_STATUSES:
        raise ReportArtifactError("Report manifest status is invalid")
    validate_report_id(manifest.get("reportId"))
    if not isinstance(manifest.get("entry"), str) or not manifest["entry"]:
        raise ReportArtifactError("Report manifest needs an entry file")
    groups = manifest.get("groups")
    if not isinstance(groups, list):
        raise ReportArtifactError("Report manifest groups must be a list")
    for group in groups:
        if not isinstance(group, dict):
            raise ReportArtifactError("Report group must be an object")
        if not isinstance(group.get("id"), str) or not group["id"]:
            raise ReportArtifactError("Report group needs an id")
        if group.get("status") not in ARTIFACT_STATUSES:
            raise ReportArtifactError("Report group status is invalid")
        if not isinstance(group.get("attributes"), dict):
            raise ReportArtifactError("Report group attributes must be an object")
        dumps = group.get("dumps")
        if not isinstance(dumps, list) or not all(
            isinstance(dump, str) for dump in dumps
        ):
            raise ReportArtifactError("Report group dumps must be relative paths")
    runner = manifest.get("runner")
    if runner is not None and not isinstance(runner, str):
        raise ReportArtifactError("Report manifest runner must be a path")
    return manifest


def serialize_payload(payload: Any) -> str:
    """Accept a dump dict or an already-serialized string/bytes."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload).decode("utf-8")
    return json.dumps(payload, ensure_ascii=False)


def write_report_artifact_file(path: Union[str, Path], content: Union[str, bytes]) -> None:
    """Publish one file atomically (upstream writeReportArtifactFile)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(content.encode("utf-8") if isinstance(content, str) else content)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class _ArtifactLock:
    """Exclusive lock file; a live publisher is never expired by elapsed time."""

    def __init__(self, root: Union[str, Path], name: str, timeout_ms: int):
        self.path = Path(root) / name
        self.timeout_ms = timeout_ms
        self._handle: Optional[Any] = None

    def __enter__(self) -> "_ArtifactLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        while True:
            try:
                self._handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if (time.monotonic() - started) * 1000 >= self.timeout_ms:
                    raise ReportArtifactError(
                        f"Timed out waiting for report artifact lock {self.path}. "
                        "Another publisher may still be running; remove the lock "
                        "only after confirming that process has exited."
                    ) from None
                time.sleep(0.02)
        os.write(self._handle, json.dumps({"pid": os.getpid()}).encode("utf-8"))
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._handle is not None:
            os.close(self._handle)
            self._handle = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def with_report_artifact_lock(
    root: Union[str, Path],
    publish: Callable[[], Any],
    timeout_ms: int = 10_000,
    lock_name: str = ".report.json.lock",
) -> Any:
    """Run ``publish`` while holding the artifact lock in ``root``."""
    with _ArtifactLock(root, lock_name, timeout_ms):
        return publish()


class ReportArtifactStore:
    """Writes execution dumps into a directory report, without rendering HTML."""

    def __init__(
        self,
        root: Union[str, Path],
        report_id: str,
        kind: str = "agent",
        reuse_existing_report: bool = False,
        entry: str = "index.html",
    ):
        if kind not in ARTIFACT_KINDS:
            raise ReportArtifactError("Report artifact kind must be agent or test")
        self.root = Path(root)
        self.report_id = validate_report_id(report_id)
        self.kind = kind
        self.reuse_existing_report = reuse_existing_report
        self.entry = entry
        self.manifest: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": kind,
            "status": "running",
            "reportId": report_id,
            "entry": entry,
            "groups": [
                {"id": report_id, "status": "running", "attributes": {}, "dumps": []}
            ],
        }
        self._execution_paths: Dict[str, str] = {}
        self._next_execution = 0
        self._finalized = False

    # -- writing -----------------------------------------------------------

    def write_execution(
        self,
        key: str,
        payload: Any,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store one execution dump; the same key overwrites its file."""
        self._assert_open()
        path = self._execution_paths.get(key)
        if path is None:
            self._next_execution += 1
            path = f"data/{self.report_id}/{self._next_execution}.json"
            self._execution_paths[key] = path
        write_report_artifact_file(self.root / path, serialize_payload(payload))
        group = self.manifest["groups"][0]
        if attributes is not None:
            group["attributes"] = dict(attributes)
        if path not in group["dumps"]:
            group["dumps"].append(path)
        self._publish()
        return path

    def write_runner(self, payload: Any) -> str:
        """Store the test-run summary that goes next to the dumps."""
        self._assert_open()
        path = f"data/{self.report_id}/runner.json"
        write_report_artifact_file(self.root / path, serialize_payload(payload))
        self.manifest["runner"] = path
        self._publish()
        return path

    def finalize(self) -> None:
        """Mark every group complete; later writes are rejected."""
        if self._finalized:
            return
        for group in self.manifest["groups"]:
            group["status"] = "complete"
        self._publish()
        self._finalized = True

    def _assert_open(self) -> None:
        if self._finalized:
            raise ReportArtifactError(
                "The report artifact stream has been finalized."
            )

    def _publish(self) -> None:
        manifest_path = self.root / "report.json"
        manifest = self.manifest

        def publish() -> None:
            nonlocal manifest
            if self.reuse_existing_report and manifest_path.exists():
                try:
                    previous = validate_manifest(
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError) as error:
                    raise ReportArtifactError(
                        f"Existing report manifest is unreadable: {manifest_path} ({error})"
                    ) from error
                if previous["kind"] != manifest["kind"] or previous["entry"] != manifest["entry"]:
                    raise ReportArtifactError(
                        "Cannot combine reports with different kinds or entries"
                    )
                merged = {group["id"]: group for group in previous["groups"]}
                for group in manifest["groups"]:
                    merged[group["id"]] = group
                manifest = {
                    **previous,
                    "groups": list(merged.values()),
                    "runner": manifest.get("runner") or previous.get("runner"),
                }
            manifest = {
                **manifest,
                "status": "complete"
                if all(group["status"] == "complete" for group in manifest["groups"])
                else "running",
            }
            validate_manifest(manifest)
            write_report_artifact_file(
                manifest_path, json.dumps(manifest, ensure_ascii=False)
            )

        with_report_artifact_lock(self.root, publish)
        self.manifest = manifest


def _validate_export_file_name(file_name: str) -> None:
    if (
        not file_name
        or file_name in (".", "..")
        or Path(file_name).name != file_name
        or file_name.endswith(".html")
    ):
        raise ReportArtifactError(
            "Midscene Test reportFileName must be one path segment without "
            f"an extension: {file_name}"
        )


def _load_report_dump_for_export(input_path: Path) -> Dict[str, Any]:
    """Read a directory artifact or a single-file HTML report into one dump."""
    from .report_viewer import _dedupe_executions, read_report_dump

    if input_path.is_dir() and (input_path / "report.json").exists():
        artifact = read_report_artifact(input_path)
        dumps = [entry["dump"] for entry in artifact["executions"]]
        if not dumps:
            raise ReportArtifactError(
                "No report execution data was found in the input."
            )
        merged = dict(dumps[0])
        executions: List[Dict[str, Any]] = []
        for dump in dumps:
            executions.extend(dump.get("executions") or [])
        merged["executions"] = _dedupe_executions(executions)
        if artifact.get("runner"):
            merged["runner"] = artifact["runner"]
        return merged
    try:
        return read_report_dump(str(input_path))
    except ValueError as error:
        raise ReportArtifactError(str(error)) from error


def export_report_artifact(
    report_path: Union[str, Path],
    output_dir: Union[str, Path],
    report_file_name: str,
    output_format: str = "single-html",
    overwrite: bool = False,
) -> str:
    """Export a report as a standalone HTML file or an HTML + asset folder.

    Accepts either a directory artifact (``report.json``) or a single-file
    report, validates the destination, then publishes atomically.
    """
    _validate_export_file_name(report_file_name)
    if output_format not in ("single-html", "html-and-external-assets"):
        raise ReportArtifactError(
            "output_format must be 'single-html' or 'html-and-external-assets'"
        )
    from .report_viewer import (
        _externalize_images,
        render_report_html,
    )

    input_path = Path(report_path).resolve()
    output = Path(output_dir).resolve()
    external = output_format == "html-and-external-assets"
    artifact = output / report_file_name
    destination = artifact / "index.html" if external else output / (
        f"{report_file_name}.html"
    )
    if input_path == destination or (
        external
        and str(input_path).startswith(f"{artifact}{os.sep}")
    ):
        raise ReportArtifactError(
            "Export destination must differ from the input report."
        )
    if not overwrite and (artifact.exists() if external else destination.exists()):
        raise ReportArtifactError(f"Report artifact already exists: {artifact}")

    dump = _load_report_dump_for_export(input_path)
    if not dump.get("executions") and not dump.get("runner"):
        raise ReportArtifactError(
            "No report execution data was found in the input."
        )

    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(dir=output, prefix=".report-export-"))
    try:
        if external:
            external_dump = _externalize_images(
                dump,
                None,
                temporary / "screenshots",
                set(),
                {"counter": 0},
                "report",
            )
            write_report_artifact_file(
                temporary / "index.html",
                render_report_html(external_dump, report_file_name),
            )
            publish_report_artifact(
                temporary, artifact, directory=True, overwrite=overwrite
            )
        else:
            entry = temporary / "index.html"
            write_report_artifact_file(
                entry, render_report_html(dump, report_file_name)
            )
            publish_report_artifact(
                entry, destination, directory=False, overwrite=overwrite
            )
        return str(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def read_report_artifact(root: Union[str, Path]) -> Dict[str, Any]:
    """Read the manifest plus every execution dump of a directory report."""
    base = Path(root)
    manifest_path = base / "report.json"
    if not manifest_path.exists():
        raise ReportArtifactError(f"No report artifact manifest at {manifest_path}")
    manifest = validate_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    executions: List[Dict[str, Any]] = []
    for group in manifest["groups"]:
        for dump_path in group["dumps"]:
            executions.append(
                {
                    "group": group["id"],
                    "path": dump_path,
                    "dump": json.loads(
                        (base / dump_path).read_text(encoding="utf-8")
                    ),
                }
            )
    runner = None
    if manifest.get("runner"):
        runner_path = base / manifest["runner"]
        if runner_path.exists():
            runner = json.loads(runner_path.read_text(encoding="utf-8"))
    return {"manifest": manifest, "executions": executions, "runner": runner}


def publish_report_artifact(
    prepared: Union[str, Path],
    destination: Union[str, Path],
    directory: bool = True,
    overwrite: bool = False,
) -> None:
    """Move a prepared artifact into place atomically (upstream publication)."""
    source = Path(prepared)
    target = Path(destination)

    def publish() -> None:
        if target.exists() and not overwrite:
            raise ReportArtifactError(f"Report artifact already exists: {target}")
        if target.is_dir() and overwrite:
            import shutil

            shutil.rmtree(target)
        elif target.exists() and overwrite:
            target.unlink()
        os.replace(source, target)

    # Per-destination lock so unrelated publications in one directory do not
    # serialize behind each other (upstream hashes the destination path).
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:16]
    with_report_artifact_lock(
        target.parent, publish, 10_000, f".report-publish-{digest}.lock"
    )


__all__ = [
    "ReportArtifactError",
    "ReportArtifactStore",
    "SCHEMA_VERSION",
    "export_report_artifact",
    "publish_report_artifact",
    "read_report_artifact",
    "serialize_payload",
    "validate_manifest",
    "validate_report_id",
    "with_report_artifact_lock",
    "write_report_artifact_file",
]