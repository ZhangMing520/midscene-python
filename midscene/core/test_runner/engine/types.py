"""Workflow engine result types (upstream test-runner/engine/types.ts)."""

from collections.abc import Callable
from typing import Any, Literal, TypedDict

CaseNodePhase = Literal["beforeEach", "steps", "afterEach"]
DocumentNodePhase = Literal["beforeAll", "afterAll"]
NodeExecutionPhase = str
CaseRunStatus = Literal["success", "failed", "not-run"]


class WorkflowReportSource(TypedDict, total=False):
    sourcePath: str
    dumpPath: str
    collection: Any


class NodeScopeTeardownResult(TypedDict, total=False):
    reportPaths: list[str]
    reportSources: list[WorkflowReportSource]


class StepRunResult(TypedDict, total=False):
    phase: str
    stepIndex: int
    node: str
    input: Any
    meta: dict[str, Any]
    continuedAfterError: bool
    waitForPreviousOperationMs: float
    operations: dict[str, Any]
    output: Any
    error: Any
    report: dict[str, Any]
    status: str
    startedAt: str
    endedAt: str
    durationMs: float
    notRunReason: str
    blockedBy: str


class CaseRunResult(TypedDict, total=False):
    caseId: str
    runId: str
    projectName: str
    attemptIndex: int
    name: str
    sourcePath: str
    caseIndex: int
    status: str
    executionStatus: str
    phases: dict[str, Any]
    cleanup: Any
    pendingOperations: list[Any]
    retryDecision: Any
    beforeEach: list[StepRunResult]
    steps: list[StepRunResult]
    afterEach: list[StepRunResult]
    executionErrors: list[Any]
    teardownErrors: list[Any]
    reportPaths: list[str]
    reportSources: list[WorkflowReportSource]
    reportScopeId: str
    startedAt: str
    endedAt: str
    durationMs: float


class WorkflowHostError(TypedDict):
    phase: str
    error: Any


class WorkflowDocumentRunResult(TypedDict, total=False):
    plan: Any
    documentId: str
    documentRunId: str
    attemptIndex: int
    projectId: str
    projectName: str
    sourcePath: str
    status: str
    executionStatus: str
    phases: dict[str, Any]
    cleanup: Any
    pendingOperations: list[Any]
    retryDecision: Any
    startedAt: str
    endedAt: str
    durationMs: float
    beforeAll: list[StepRunResult]
    afterAll: list[StepRunResult]
    executionErrors: list[Any]
    hostErrors: list[WorkflowHostError]
    teardownErrors: list[Any]
    reportPaths: list[str]
    reportSources: list[WorkflowReportSource]
    reportScopeId: str


class CaseExecutionContext(TypedDict):
    caseId: str
    runId: str
    projectName: str
    attemptIndex: int
    name: str
    sourcePath: str
    caseIndex: int


class NodeCaseContext(TypedDict, total=False):
    caseId: str
    runId: str
    projectName: str
    attemptIndex: int
    name: str
    sourcePath: str
    caseIndex: int
    phase: str
    stepIndex: int


class NodeDocumentContext(TypedDict, total=False):
    documentId: str
    documentRunId: str
    projectId: str
    projectName: str
    sourcePath: str
    phase: str
    stepIndex: int


class StepExecutionInfo(TypedDict, total=False):
    scope: str
    node: str
    stepCount: int
    case: NodeCaseContext
    document: NodeDocumentContext


class RunCollectedCaseOptions(TypedDict, total=False):
    teardownTimeoutMs: Callable[[], float]
    resolveNode: Callable[[str], Any]
    beforeEach: list[dict[str, Any]]
    afterEach: list[dict[str, Any]]
    context: Any
    projectName: str
    attemptIndex: int
    signal: Any
    defaultTimeoutMs: float
    onStepStart: Callable[..., Any]
    onStepResult: Callable[..., Any]
    onResult: Callable[[CaseRunResult], Any]
    createRunId: Callable[[], str]
    reportScopeId: str


class CaseRunOutcome(TypedDict, total=False):
    caseId: str
    projectName: str
    name: str
    sourcePath: str
    caseIndex: int
    onFailure: str
    status: str
    run: CaseRunResult
    attempts: list[CaseRunResult]
    notRunReason: str


class WorkflowDocumentExecutionResult(TypedDict):
    document: WorkflowDocumentRunResult
    cases: list[CaseRunOutcome]


class RunWorkflowDocumentOptions(TypedDict, total=False):
    setupTimeoutMs: float
    teardownTimeoutMs: Callable[[], float]
    plan: Any
    documentSetup: Any
    documentAttemptIndex: int
    resolveNode: Callable[[str], Any]
    project: Any
    projectContext: Any
    retry: int
    signal: Any
    defaultTimeoutMs: float
    shouldStop: Callable[[], bool]
    stopReason: Callable[[], str]
    isFatalError: Callable[[CaseRunResult], bool]
    onCaseStart: Callable[..., Any]
    onStepStart: Callable[..., Any]
    onStepResult: Callable[..., Any]
    onCaseResult: Callable[..., Any]
    onCaseOutcome: Callable[..., Any]
    onDocumentResult: Callable[..., Any]
    createCaseRunId: Callable[..., str]
    createDocumentRunId: Callable[..., str]
    resolveCaseReportScopeId: Callable[..., str | None]


class CreateDocumentRuntimeOptions(TypedDict, total=False):
    setupTimeoutMs: float
    teardownTimeoutMs: Callable[[], float]
    plan: Any
    documentSetup: Any
    documentAttemptIndex: int
    resolveNode: Callable[[str], Any]
    project: Any
    projectContext: Any
    signal: Any
    defaultTimeoutMs: float
    onStepStart: Callable[..., Any]
    onStepResult: Callable[..., Any]
    onResult: Callable[..., Any]
    createDocumentRunId: Callable[[], str]


class WorkflowDocumentRuntime(TypedDict, total=False):
    signal: Any
    context: Any
    canRunCases: bool


class ProjectRuntimeOptions(TypedDict, total=False):
    setupTimeoutMs: float
    teardownTimeoutMs: Callable[[], float]
    project: Any
    setup: Any
    signal: Any


class ProjectRuntimeResult(TypedDict, total=False):
    projectName: str
    status: str
    setupError: Any
    teardownErrors: list[Any]
    cleanup: Any
    pendingOperations: list[Any]
    startedAt: str
    endedAt: str
    durationMs: float


class CaseRunnerOptions(TypedDict, total=False):
    nodes: list[Any]
    context: Any
