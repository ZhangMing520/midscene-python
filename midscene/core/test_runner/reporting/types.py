"""Report input types (upstream test-runner/reporting/types.ts)."""

from typing import Any, Dict, List, TypedDict


class RunReportCaseInput(TypedDict, total=False):
    caseId: str
    projectName: str
    name: str
    sourcePath: str
    caseIndex: int
    onFailure: str
    status: str
    run: Any
    attempts: List[Any]
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
    cases: List[RunReportCaseInput]
    plans: List[Any]
    documents: List[Any]
    collectionErrors: List[Dict[str, Any]]


class RunReportInput(TypedDict, total=False):
    operationLog: Dict[str, str]
    runId: str
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    summary: Any
    projects: List[RunReportProjectInput]
    errors: List[Any]
