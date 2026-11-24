"""Project execution records into report input (upstream reporting/execution-record.ts)."""

import datetime
from typing import Any, cast

from midscene.core.test_runner.execution_record import (
    WorkflowExecutionRecord,
    execution_record_to_result,
)
from midscene.core.test_runner.reporting.types import (
    RunReportInput,
    RunReportProjectInput,
)


def _parse_iso(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def execution_records_to_report_input(
    records: list[WorkflowExecutionRecord],
    options: dict[str, Any],
) -> RunReportInput:
    """Project complete invocations without changing their legacy/API state."""
    if not records:
        raise ValueError("A report requires at least one execution record.")

    grouped: dict[str, list[WorkflowExecutionRecord]] = {}
    for record in records:
        project_id = record["document"]["projectId"]
        grouped.setdefault(project_id, []).append(record)

    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "notRun": 0,
        "filtered": 0,
        "collectionErrors": 0,
        "documentFailures": 0,
        "projectFailures": 0,
    }
    projects: list[RunReportProjectInput] = []
    for project_id, group in grouped.items():
        platform = group[0].get("platform")
        name = group[0].get("projectName") or platform
        latest: dict[str, WorkflowExecutionRecord] = {}
        current_invocation: dict[str, str] = {}
        for record in group:
            document_id = record["document"]["documentId"]
            if record.get("attemptIndex") == 0 or document_id not in current_invocation:
                current_invocation[document_id] = record["runId"]
            latest[current_invocation[document_id]] = record

        for record in latest.values():
            execution = record.get("execution")
            outcomes = execution.get("cases") if execution is not None else None
            document = execution.get("document") if execution is not None else None
            summary["total"] += len(record["document"]["cases"])
            if outcomes is not None:
                summary["passed"] += sum(
                    1 for item in outcomes if item.get("status") == "success"
                )
                summary["failed"] += sum(
                    1 for item in outcomes if item.get("status") == "failed"
                )
                summary["notRun"] += sum(
                    1 for item in outcomes if item.get("status") == "not-run"
                )
            else:
                summary["notRun"] += len(record["document"]["cases"])
            if (
                record.get("setupError") is not None
                or record.get("executionError") is not None
                or record.get("reportError") is not None
                or record.get("publicationErrors")
                or record.get("observerErrors")
                or record.get("cleanupErrors")
                or (document or {}).get("status") == "failed"
            ):
                summary["documentFailures"] += 1

        results = [execution_record_to_result(record) for record in group]
        documents = [result["document"] for result in results]
        projects.append(
            {
                "projectId": project_id,
                "name": cast(str, name),
                "platform": cast(str, platform),
                "status": (
                    "failed"
                    if any(
                        record.get("status") == "failed" for record in latest.values()
                    )
                    else "success"
                ),
                "retry": max(record.get("attemptIndex", 0) for record in group),
                "documents": documents,
                "collectionErrors": [],
                "cases": [
                    {
                        **outcome,
                        "documentId": result["document"]["documentId"],
                        "documentRunId": result["document"]["documentRunId"],
                    }
                    for result in results
                    for outcome in result["cases"]
                ],
            }
        )

    started_at = (
        options.get("startedAt") or sorted(record["startedAt"] for record in records)[0]
    )
    ended_at = (
        options.get("endedAt") or sorted(record["endedAt"] for record in records)[-1]
    )
    start = _parse_iso(started_at)
    end = _parse_iso(ended_at)
    duration_ms = (
        max(0.0, (end - start).total_seconds() * 1000)
        if start is not None and end is not None
        else 0.0
    )
    return {
        "runId": options["runId"],
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationMs": duration_ms,
        "status": (
            "failed"
            if any(project["status"] == "failed" for project in projects)
            else "success"
        ),
        "summary": summary,
        "projects": projects,
    }


__all__ = ["execution_records_to_report_input"]
