"""Report input types (upstream test-runner/reporting/types.ts)."""

from typing import Any, TypedDict


class RunReportCaseInput(TypedDict, total=False):
    caseId: str
    projectName: str
    name: str
    sourcePath: str
    caseIndex: int
    onFailure: str
    status: str
    run: Any
    attempts: list[Any]
    notRunReason: str
    documentId: str
    documentRunId: str


class RunReportProjectInput(TypedDict, total=False):
    projectId: str
    name: str
    platform: str
    status: str
    retry: int
    lifecycle: Any
    cases: list[RunReportCaseInput]
    plans: list[Any]
    documents: list[Any]
    collectionErrors: list[dict[str, Any]]


class RunReportInput(TypedDict, total=False):
    operationLog: dict[str, str]
    runId: str
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    summary: Any
    projects: list[RunReportProjectInput]
    errors: list[Any]
