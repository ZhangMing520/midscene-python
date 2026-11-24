"""Midscene Test run report types (upstream core/src/test-run-report.ts).

This module mirrors the JSON shape of the upstream test-runner report. The
report aggregation helpers will be ported on top of these types.
"""

from typing import Any, TypedDict

TEST_RUN_REPORT_SCRIPT_TYPE = "midscene_test_run_dump"
TEST_RUN_REPORT_SCHEMA_VERSION = 1

TestRunReportRunStatus = str  # 'success' | 'failed'
TestRunReportCaseStatus = str  # run status | 'not-run'
TestRunReportStepPhase = str  # beforeAll | beforeEach | steps | afterEach | afterAll


class TestRunReportValue(TypedDict, total=False):
    value: Any
    truncatedPaths: list[str]
    redactedPaths: list[str]


class TestRunReportError(TypedDict, total=False):
    format: str
    name: str
    message: str
    stack: str
    code: str
    details: TestRunReportValue
    cause: "TestRunReportError"
    errors: list["TestRunReportError"]
    truncated: bool


class TestRunReportOperationReference(TypedDict, total=False):
    operationId: str
    scopeId: str
    stepId: str
    node: str


class TestRunReportCleanup(TypedDict, total=False):
    status: str  # not-required | completed | pending | failed
    capturedAt: str
    operationId: str
    blockingOperations: list[TestRunReportOperationReference]
    error: TestRunReportError


class TestRunReportRetryDecision(TypedDict, total=False):
    scope: str  # case | document
    retryCount: int
    attemptIndex: int
    decision: str  # retry | stop
    reason: str


class TestRunReportPhaseResult(TypedDict, total=False):
    status: str  # success | failed | not-run | not-required
    plannedStepCount: int
    executedStepCount: int


class TestRunReportHostError(TypedDict, total=False):
    phase: str  # setup | execution | cleanup | report | publication | observer
    error: Any


class TestRunReportDiagnostic(TypedDict, total=False):
    level: str
    code: str
    message: str
    scopeId: str
    executionId: str
    sourcePaths: list[str]
    stepId: str
    error: TestRunReportError


class ReportModelUsageSummary(TypedDict, total=False):
    modelName: str
    callCount: int
    promptTokens: int
    cachedInputTokens: int
    completionTokens: int
    totalTokens: int
    modelCallTimeMs: int


class TestRunReportMetrics(TypedDict, total=False):
    models: list[ReportModelUsageSummary]
    modelCallCount: int
    modelTimeMs: int
    promptTokens: int
    cachedInputTokens: int
    completionTokens: int
    totalTokens: int
    collection: dict[str, Any]


class TestRunReportSnapshotCollection(TypedDict, total=False):
    status: str  # complete | partial
    capturedAt: str
    reason: str


class TestRunReportAgentDetail(TypedDict, total=False):
    reportId: str
    executionId: str


class TestRunReportOperationEvent(TypedDict, total=False):
    operationId: str
    operationKind: str  # node | resource | acquisition | cleanup | readiness
    kind: (
        str  # started | cancel-requested | settled | runner-returned | cleanup-deferred
    )
    at: str
    stepId: str
    scopeId: str
    node: str
    status: str  # success | failed | not-run
    pending: bool
    error: TestRunReportError
    blockingOperations: list[TestRunReportOperationReference]


class TestRunReportPlannedStep(TypedDict, total=False):
    id: str
    phase: str
    stepIndex: int
    node: str
    title: str
    input: TestRunReportValue
    inputMode: str  # template | resolved
    timeoutMs: float
    continueOnError: bool


class TestRunReportCasePlan(TypedDict, total=False):
    caseId: str
    name: str
    caseIndex: int
    selected: bool
    tags: list[str]
    onFailure: str
    beforeEach: list[TestRunReportPlannedStep]
    steps: list[TestRunReportPlannedStep]
    afterEach: list[TestRunReportPlannedStep]


class TestRunReportDocumentPlan(TypedDict, total=False):
    documentId: str
    sourcePath: str
    sourceYaml: TestRunReportValue
    retry: dict[str, Any]
    beforeAll: list[TestRunReportPlannedStep]
    cases: list[TestRunReportCasePlan]
    afterAll: list[TestRunReportPlannedStep]


class TestRunReportStep(TypedDict, total=False):
    id: str
    planStepId: str
    phase: str
    stepIndex: int
    node: str
    title: str
    continuedAfterError: bool
    waitForPreviousOperationMs: float
    input: TestRunReportValue
    output: dict[str, Any]
    error: TestRunReportError
    agentDetails: list[TestRunReportAgentDetail]
    agentDetailDiagnostic: str
    metrics: TestRunReportMetrics
    evidenceCollection: dict[str, Any]
    operations: dict[str, Any]
    status: str
    notRunReason: str
    blockedBy: str
    startedAt: str
    endedAt: str
    durationMs: float


class TestRunReportAttempt(TypedDict, total=False):
    attemptId: str
    attemptIndex: int
    status: str
    executionStatus: str
    phases: dict[str, TestRunReportPhaseResult]
    cleanup: TestRunReportCleanup
    pendingOperations: list[TestRunReportOperationReference]
    retryDecision: TestRunReportRetryDecision
    startedAt: str
    endedAt: str
    durationMs: float
    beforeEach: list[TestRunReportStep]
    steps: list[TestRunReportStep]
    afterEach: list[TestRunReportStep]
    teardownErrors: list[TestRunReportError]
    hostErrors: list[TestRunReportHostError]
    scopeReportIds: list[str]


class TestRunReportCase(TypedDict, total=False):
    plan: TestRunReportCasePlan
    caseId: str
    name: str
    caseIndex: int
    status: str
    notRunReason: str
    attempts: list[TestRunReportAttempt]


class TestRunReportDocument(TypedDict, total=False):
    plan: TestRunReportDocumentPlan
    documentId: str
    logicalDocumentId: str
    documentRunId: str
    attemptIndex: int
    sourcePath: str
    status: str
    executionStatus: str
    phases: dict[str, TestRunReportPhaseResult]
    cleanup: TestRunReportCleanup
    pendingOperations: list[TestRunReportOperationReference]
    retryDecision: TestRunReportRetryDecision
    startedAt: str
    endedAt: str
    durationMs: float
    beforeAll: list[TestRunReportStep]
    cases: list[TestRunReportCase]
    afterAll: list[TestRunReportStep]
    teardownErrors: list[TestRunReportError]
    hostErrors: list[TestRunReportHostError]
    scopeReportIds: list[str]
    attempts: list[dict[str, Any]]


class TestRunReportCollectionError(TypedDict, total=False):
    sourcePath: str
    error: TestRunReportError


class TestRunReportProjectLifecycle(TypedDict, total=False):
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    setupError: TestRunReportError
    teardownErrors: list[TestRunReportError]
    cleanup: TestRunReportCleanup
    pendingOperations: list[TestRunReportOperationReference]


class TestRunReportProject(TypedDict, total=False):
    plans: list[TestRunReportDocumentPlan]
    projectId: str
    name: str
    platform: str
    status: str
    retry: int
    lifecycle: TestRunReportProjectLifecycle
    documents: list[TestRunReportDocument]
    collectionErrors: list[TestRunReportCollectionError]


class TestRunReportSummary(TypedDict, total=False):
    total: int
    passed: int
    failed: int
    notRun: int
    filtered: int
    collectionErrors: int
    documentFailures: int
    projectFailures: int


class TestRunReportDump(TypedDict, total=False):
    schemaVersion: int
    kind: str
    runId: str
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    summary: TestRunReportSummary
    metrics: TestRunReportMetrics
    executionMetrics: dict[str, TestRunReportMetrics]
    projects: list[TestRunReportProject]
    diagnostics: list[TestRunReportDiagnostic]
    operationLogs: list[dict[str, str]]


class TestRunReportSource(TypedDict, total=False):
    scopeId: str
    sourcePath: str
    dumpPath: str
    collection: TestRunReportSnapshotCollection


class IndexedTestRunReportSource(TypedDict, total=False):
    reportId: str
    scopeId: str
    sourcePath: str
    executionIds: list[str]
    collection: TestRunReportSnapshotCollection


class TestRunReportSourceIndex(TypedDict, total=False):
    sources: list[IndexedTestRunReportSource]
    metrics: TestRunReportMetrics
    executionMetrics: dict[str, TestRunReportMetrics]
    capturedMetrics: TestRunReportMetrics
    diagnostics: list[TestRunReportDiagnostic]


class AssembleTestRunReportOptions(TypedDict, total=False):
    outputDir: str
    outputFormat: str
    reportFileName: str
    sources: list[TestRunReportSource]
    overwrite: bool


__all__ = [
    "TEST_RUN_REPORT_SCRIPT_TYPE",
    "TEST_RUN_REPORT_SCHEMA_VERSION",
    "AssembleTestRunReportOptions",
    "IndexedTestRunReportSource",
    "ReportModelUsageSummary",
    "TestRunReportAgentDetail",
    "TestRunReportAttempt",
    "TestRunReportCase",
    "TestRunReportCasePlan",
    "TestRunReportCleanup",
    "TestRunReportCollectionError",
    "TestRunReportDiagnostic",
    "TestRunReportDocument",
    "TestRunReportDocumentPlan",
    "TestRunReportDump",
    "TestRunReportError",
    "TestRunReportHostError",
    "TestRunReportMetrics",
    "TestRunReportOperationEvent",
    "TestRunReportOperationReference",
    "TestRunReportPhaseResult",
    "TestRunReportPlannedStep",
    "TestRunReportProject",
    "TestRunReportProjectLifecycle",
    "TestRunReportRetryDecision",
    "TestRunReportSnapshotCollection",
    "TestRunReportSource",
    "TestRunReportSourceIndex",
    "TestRunReportStep",
    "TestRunReportSummary",
    "TestRunReportValue",
]
