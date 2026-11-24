"""Directory report artifact storage (upstream dump/report-artifact-store.ts).

A directory report is a folder instead of a single HTML file:

    <root>/report.json            manifest: kind, status, groups, dumps
    <root>/data/<reportId>/1.json one execution dump per file
    <root>/data/<reportId>/runner.json optional test-run summary

Every write is atomic (temp file + rename) and the manifest is only replaced
while holding a lock file, so a reader never sees a truncated artifact and two
publishers never clobber each other.
"""

import json
import math
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REPORT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
REPORT_ARTIFACT_PATH_PATTERN = re.compile(
    r"^(?:\./)?[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$"
)
ARTIFACT_KINDS = ("agent", "test")
ARTIFACT_STATUSES = ("running", "complete")


class ReportArtifactError(ValueError):
    """Raised for an invalid or inconsistent report artifact."""


def validate_report_id(report_id: object) -> str:
    if not isinstance(report_id, str) or not REPORT_ID_PATTERN.match(report_id):
        raise ReportArtifactError("Invalid report artifact ID")
    return report_id


def assert_report_artifact_path(path: Any) -> str:
    """Reject artifact references that could escape the report directory."""
    stripped = path[2:] if isinstance(path, str) and path.startswith("./") else path
    if (
        not isinstance(path, str)
        or not REPORT_ARTIFACT_PATH_PATTERN.match(path)
        or any(part in (".", "..") for part in stripped.split("/"))
    ):
        raise ReportArtifactError(f"Invalid report artifact path: {path}")
    return path


def validate_manifest(manifest: Any) -> dict[str, Any]:
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
    entry = manifest.get("entry")
    if (
        not isinstance(entry, str)
        or not entry.endswith(".html")
        or "/" in entry
        or "\\" in entry
    ):
        raise ReportArtifactError("Report manifest needs an HTML entry file")
    groups = manifest.get("groups")
    if not isinstance(groups, list):
        raise ReportArtifactError("Report manifest groups must be a list")
    seen_ids = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ReportArtifactError("Report group must be an object")
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            raise ReportArtifactError("Report group needs an id")
        if group_id in seen_ids:
            raise ReportArtifactError("Report group ids must be unique")
        seen_ids.add(group_id)
        if group.get("status") not in ARTIFACT_STATUSES:
            raise ReportArtifactError("Report group status is invalid")
        attributes = group.get("attributes")
        if not isinstance(attributes, dict):
            raise ReportArtifactError("Report group attributes must be an object")
        for attribute in attributes.values():
            if not isinstance(attribute, (str, int, float, bool)) or (
                isinstance(attribute, (int, float))
                and not isinstance(attribute, bool)
                and not math.isfinite(attribute)
            ):
                raise ReportArtifactError(
                    "Report group attributes must be portable values"
                )
        dumps = group.get("dumps")
        if not isinstance(dumps, list):
            raise ReportArtifactError("Report group dumps must be relative paths")
        for dump in dumps:
            assert_report_artifact_path(dump)
    if groups:
        expected_status = (
            "complete"
            if all(group["status"] == "complete" for group in groups)
            else "running"
        )
        if manifest["status"] != expected_status:
            raise ReportArtifactError(
                "Report manifest status is inconsistent with its groups"
            )
    runner = manifest.get("runner")
    if runner is not None:
        assert_report_artifact_path(runner)
    return manifest


def parse_report_artifact_manifest(value: Any) -> dict[str, Any]:
    """Validate a manifest value against the portable artifact contract."""
    try:
        return validate_manifest(value)
    except ReportArtifactError as error:
        raise ReportArtifactError(
            "Invalid or unsupported report artifact manifest"
        ) from error


def serialize_payload(payload: Any) -> str:
    """Accept a dump dict or an already-serialized string/bytes."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload).decode("utf-8")
    return json.dumps(payload, ensure_ascii=False)


def write_report_artifact_file(path: str | Path, content: str | bytes) -> None:
    """Publish one file atomically (upstream writeReportArtifactFile)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(
                content.encode("utf-8") if isinstance(content, str) else content
            )
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class _ArtifactLock:
    """Exclusive lock file; a live publisher is never expired by elapsed time."""

    def __init__(self, root: str | Path, name: str, timeout_ms: int):
        self.path = Path(root) / name
        self.timeout_ms = timeout_ms
        self._handle: Any | None = None

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
    root: str | Path,
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
        root: str | Path,
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
        self.manifest: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": kind,
            "status": "running",
            "reportId": report_id,
            "entry": entry,
            "groups": [
                {"id": report_id, "status": "running", "attributes": {}, "dumps": []}
            ],
        }
        self._execution_paths: dict[str, str] = {}
        self._next_execution = 0
        self._finalized = False
        self._has_published = False

    # -- writing -----------------------------------------------------------

    def write_execution(
        self,
        key: str,
        payload: Any,
        attributes: dict[str, Any] | None = None,
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
        """Mark this store's own group complete; later writes are rejected."""
        if self._finalized:
            return
        # Only the group owned by this store is sealed. Other writers' groups
        # that appear in the merged manifest must keep their own status.
        self.manifest["groups"][0]["status"] = "complete"
        self._publish()
        self._finalized = True

    def _assert_open(self) -> None:
        if self._finalized:
            raise ReportArtifactError("The report artifact stream has been finalized.")

    def _publish(self) -> None:
        manifest_path = self.root / "report.json"
        manifest = self.manifest

        def publish() -> None:
            nonlocal manifest
            if (
                self.reuse_existing_report or self._has_published
            ) and manifest_path.exists():
                try:
                    previous = validate_manifest(
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError) as error:
                    raise ReportArtifactError(
                        f"Existing report manifest is unreadable: {manifest_path} ({error})"
                    ) from error
                if (
                    previous["kind"] != manifest["kind"]
                    or previous["entry"] != manifest["entry"]
                ):
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
            # Keep the store's own manifest immutable so subsequent writes only
            # mutate this writer's group; other groups are re-merged on publish.
            self._has_published = True

        with_report_artifact_lock(self.root, publish)


__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_STATUSES",
    "REPORT_ARTIFACT_PATH_PATTERN",
    "REPORT_ID_PATTERN",
    "ReportArtifactError",
    "ReportArtifactStore",
    "SCHEMA_VERSION",
    "assert_report_artifact_path",
    "parse_report_artifact_manifest",
    "serialize_payload",
    "validate_manifest",
    "validate_report_id",
    "with_report_artifact_lock",
    "write_report_artifact_file",
]
