"""Workflow document parser types (upstream test-runner/parser/types.ts)."""

from typing import Any, Dict, List, TypedDict


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
    input: Dict[str, Any]
    templateInput: Dict[str, Any]
    meta: NormalizedStepMeta


class CaseDefinition(TypedDict, total=False):
    name: str
    tags: List[str]
    steps: List[Any]


class WorkflowDocumentDefinition(TypedDict, total=False):
    beforeAll: List[Dict[str, Any]]
    beforeEach: List[Dict[str, Any]]
    cases: List[CaseDefinition]
    afterEach: List[Dict[str, Any]]
    afterAll: List[Dict[str, Any]]


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
    definition: Dict[str, Any]


class CollectedDocumentLifecycle(TypedDict):
    beforeAll: List[NormalizedStep]
    beforeEach: List[NormalizedStep]
    afterEach: List[NormalizedStep]
    afterAll: List[NormalizedStep]


class CollectedWorkflowDocument(TypedDict, total=False):
    documentId: str
    projectId: str
    sourcePath: str
    sourceYaml: Any
    lifecycle: CollectedDocumentLifecycle
    cases: List[CollectedCase]
