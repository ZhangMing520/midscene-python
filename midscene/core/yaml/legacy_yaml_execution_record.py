"""Legacy YAML execution records (upstream yaml/legacy-yaml-execution-record.ts)."""

import datetime
from typing import Any, Dict, List

from midscene.core.test_runner.execution_record import WorkflowExecutionRecord


def _to_iso(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return (
        value.astimezone(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def yaml_platform(script: Dict[str, Any]) -> str:
    for key in ("android", "ios", "harmony", "computer", "interface"):
        # Match JS truthiness: an empty target block is still a target.
        if script.get(key) is not None:
            return key
    return "web"


def create_legacy_yaml_execution_record(
    options: Dict[str, Any],
) -> WorkflowExecutionRecord:
    """Convert compatibility-host state into the shared immutable run record."""
    execution = options.get("execution")
    cleanup_errors: List[Any] = list(options.get("cleanupErrors") or [])
    failed = (
        options.get("setupError") is not None
        or options.get("executionError") is not None
        or bool(cleanup_errors)
        or bool(options.get("aborted"))
        or (execution or {}).get("document", {}).get("status") == "failed"
        or any(
            outcome.get("status") != "success"
            for outcome in (execution or {}).get("cases") or []
        )
    )
    document = options["document"]
    started_at = options["startedAt"]
    ended_at = options["endedAt"]
    record: WorkflowExecutionRecord = {
        "runId": options["runId"],
        "attemptIndex": options["attemptIndex"],
        "sourcePath": document.get("sourcePath"),
        "platform": yaml_platform(options.get("script") or {}),
        "document": document,
        "status": "failed" if failed else "success",
        "startedAt": _to_iso(started_at),
        "endedAt": _to_iso(ended_at),
        "durationMs": max(
            0.0, (ended_at - started_at).total_seconds() * 1000
        ),
        "cleanupErrors": cleanup_errors,
        "outputs": dict(options.get("outputs") or {}),
        "reportPaths": [options["reportFile"]] if options.get("reportFile") else [],
    }
    if options.get("projectName") is not None:
        record["projectName"] = options["projectName"]
    if execution is not None:
        record["execution"] = execution
    if options.get("setupError") is not None:
        record["setupError"] = options["setupError"]
    if options.get("executionError") is not None:
        record["executionError"] = options["executionError"]
    publication_errors = list(options.get("publicationErrors") or [])
    if publication_errors:
        record["publicationErrors"] = publication_errors
    children = list(options.get("children") or [])
    if children:
        record["children"] = children
    return record


__all__ = ["create_legacy_yaml_execution_record", "yaml_platform"]
