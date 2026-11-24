"""Workflow document parser types (upstream test-runner/parser/types.ts)."""

from typing import Any, TypedDict


class StepMetaInput(TypedDict, total=False):
    timeout: float
    continueOnError: bool


class SourceLocation(TypedDict):
    line: int
    column: int


class NormalizedStepMeta(TypedDict, total=False):
    sourceLocation: SourceLocation
    captureResult: bool
    timeoutMs: float
    continueOnError: bool
    resultName: str


class NormalizedStep(TypedDict, total=False):
    node: str
    input: dict[str, Any]
    templateInput: dict[str, Any]
    meta: NormalizedStepMeta


class CaseDefinition(TypedDict, total=False):
    name: str
    tags: list[str]
    steps: list[Any]


class WorkflowDocumentDefinition(TypedDict, total=False):
    beforeAll: list[dict[str, Any]]
    beforeEach: list[dict[str, Any]]
    cases: list[CaseDefinition]
    afterEach: list[dict[str, Any]]
    afterAll: list[dict[str, Any]]


class WorkflowDocumentSource(TypedDict, total=False):
    projectId: str
    projectName: str
    sourcePath: str
    absolutePath: str
    invocationIndex: int


class CollectedCase(TypedDict):
    caseId: str
    projectId: str
    sourcePath: str
    caseIndex: int
    definition: dict[str, Any]


class CollectedDocumentLifecycle(TypedDict):
    beforeAll: list[NormalizedStep]
    beforeEach: list[NormalizedStep]
    afterEach: list[NormalizedStep]
    afterAll: list[NormalizedStep]


class CollectedWorkflowDocument(TypedDict, total=False):
    documentId: str
    projectId: str
    sourcePath: str
    sourceYaml: Any
    lifecycle: CollectedDocumentLifecycle
    cases: list[CollectedCase]
