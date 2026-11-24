"""Execution records for the workflow entry adapter (upstream execution-record.ts)."""

import json
from typing import Any, TypedDict

from midscene.core.test_runner.engine.types import (
    WorkflowDocumentExecutionResult,
    WorkflowHostError,
    WorkflowReportSource,
)
from midscene.core.test_runner.parser.types import CollectedWorkflowDocument
from midscene.core.test_runner.reporting.test_plan import build_test_run_report_plan


class WorkflowExecutionRecord(TypedDict, total=False):
    """One complete document invocation, including work outside the pure kernel."""

    runId: str
    attemptIndex: int
    sourcePath: str
    platform: str
    projectName: str
    document: CollectedWorkflowDocument
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    execution: WorkflowDocumentExecutionResult
    setupError: Any
    executionError: Any
    cleanupErrors: list[Any]
    outputs: dict[str, Any]
    reportPaths: list[str]
    reportSources: list[WorkflowReportSource]
    children: list["WorkflowExecutionRecord"]
    reportError: Any
    publicationErrors: list[Any]
    observerErrors: list[Any]


def execution_record_to_result(record: WorkflowExecutionRecord) -> dict[str, Any]:
    """Complete host facts as a kernel result. Report and summary consume this view."""
    execution = (record.get("execution") or {}).get("document")
    host_errors: list[WorkflowHostError] = list(
        (execution or {}).get("hostErrors") or []
    )

    def add(phase: str, error: Any) -> None:
        if error is not None:
            host_errors.append({"phase": phase, "error": error})

    add("setup", record.get("setupError"))
    add("execution", record.get("executionError"))
    for error in record.get("cleanupErrors") or []:
        add("cleanup", error)
    add("report", record.get("reportError"))
    for error in record.get("publicationErrors") or []:
        add("publication", error)
    for error in record.get("observerErrors") or []:
        add("observer", error)

    document = record["document"]
    project_name = (
        record.get("projectName")
        or (execution or {}).get("projectName")
        or record.get("platform")
    )
    result_document: dict[str, Any] = {
        "plan": (execution or {}).get("plan") or build_test_run_report_plan(document),
        "documentId": document["documentId"],
        "documentRunId": record["runId"],
        "attemptIndex": record["attemptIndex"],
        "projectId": document["projectId"],
        "projectName": project_name,
        "sourcePath": record["sourcePath"],
        # Case failures are counted separately; host failures must not convert
        # successful Cases into retryable action failures.
        "status": (
            "failed"
            if host_errors or (execution or {}).get("status") == "failed"
            else "success"
        ),
        "startedAt": record["startedAt"],
        "endedAt": record["endedAt"],
        "durationMs": record["durationMs"],
        "beforeAll": (execution or {}).get("beforeAll") or [],
        "afterAll": (execution or {}).get("afterAll") or [],
        "reportScopeId": (execution or {}).get("reportScopeId") or record["runId"],
        "reportPaths": list(record.get("reportPaths") or []),
    }
    if host_errors:
        result_document["hostErrors"] = host_errors
    if (execution or {}).get("executionErrors"):
        result_document["executionErrors"] = execution["executionErrors"]
    if (execution or {}).get("teardownErrors"):
        result_document["teardownErrors"] = execution["teardownErrors"]
    if record.get("reportSources"):
        result_document["reportSources"] = list(record["reportSources"])

    execution_result = record.get("execution")
    if execution_result and "cases" in execution_result:
        cases = execution_result["cases"]
    else:
        cases = [
            {
                "caseId": item["caseId"],
                "projectName": project_name,
                "name": item["definition"].get("name"),
                "sourcePath": item.get("sourcePath"),
                "caseIndex": item.get("caseIndex"),
                "status": "not-run",
                "notRunReason": "document-start-failed",
            }
            for item in document["cases"]
        ]
    return {"document": result_document, "cases": cases}


def _error_payload(value: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": type(value).__name__,
        "message": str(value),
    }
    code = getattr(value, "code", None)
    if code is not None:
        payload["code"] = code
    details = getattr(value, "details", None)
    if details is not None:
        payload["details"] = details
    errors = getattr(value, "errors", None)
    if errors is not None:
        payload["errors"] = list(errors)
    return payload


def serialize_workflow_execution_record(record: WorkflowExecutionRecord) -> str:
    return serialize_workflow_value(record)


def serialize_workflow_value(value: Any) -> str:
    """The same error-preserving encoding for entry results and worker envelopes."""

    def default(item: Any) -> Any:
        if isinstance(item, BaseException):
            return _error_payload(item)
        if hasattr(item, "isoformat"):
            return item.isoformat()
        raise TypeError(
            f"Object of type {type(item).__name__} is not JSON serializable"
        )

    return json.dumps(value, default=default, indent=2, ensure_ascii=False)


__all__ = [
    "WorkflowExecutionRecord",
    "execution_record_to_result",
    "serialize_workflow_execution_record",
    "serialize_workflow_value",
]
