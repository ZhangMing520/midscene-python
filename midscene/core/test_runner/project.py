"""Project and setup definition types (upstream test-runner/project.ts)."""

from typing import Any, Awaitable, Callable, Dict, List, TypedDict

JsonValue = Any


class TestFileSelection(TypedDict, total=False):
    include: List[str]
    exclude: List[str]


class TestTagSelection(TypedDict, total=False):
    include: List[str]
    exclude: List[str]


class ExecutionProjectDefinition(TypedDict, total=False):
    name: str
    setup: Any
    fileSetup: Any
    maxConcurrentFiles: int
    nodes: List[Any]
    files: TestFileSelection
    tags: TestTagSelection
    retry: int
    variables: Dict[str, JsonValue]


class ResolvedExecutionProject(TypedDict, total=False):
    projectId: str
    name: str
    setup: Any
    fileSetup: Any
    maxConcurrentFiles: int
    files: TestFileSelection
    tags: Dict[str, List[str]]
    retry: int
    variables: Dict[str, JsonValue]


class WorkflowExecutionProject(TypedDict, total=False):
    """The document kernel does not consume selection rules or host setup."""

    projectId: str
    name: str
    retry: int


class ProjectSetupContext(TypedDict, total=False):
    project: ResolvedExecutionProject
    env: Dict[str, str]
    signal: Any
    onTeardown: Callable[[Any], None]


class ProjectTeardownContext(TypedDict, total=False):
    project: ResolvedExecutionProject
    context: Any
    status: str
    setupError: Any


class ProjectSetupDefinition(TypedDict, total=False):
    name: str
    setup: Callable[[ProjectSetupContext], Awaitable[Any]]


class FileSetupContext(TypedDict, total=False):
    project: ResolvedExecutionProject
    projectContext: Any
    file: Dict[str, str]
    env: Dict[str, str]
    signal: Any
    onTeardown: Callable[[Callable[[], Awaitable[None]]], None]


class FileSetupDefinition(TypedDict, total=False):
    name: str
    setup: Callable[[FileSetupContext], Awaitable[Any]]


class DocumentSetupContext(TypedDict, total=False):
    project: WorkflowExecutionProject
    projectContext: Any
    document: Dict[str, Any]
    signal: Any
    onTeardown: Callable[[Any], None]


class DocumentSetupDefinition(TypedDict, total=False):
    name: str
    setup: Callable[[DocumentSetupContext], Awaitable[Any]]
    onDocumentResult: Callable[[Any, Any], Awaitable[None]]


__all__ = [
    "DocumentSetupContext",
    "DocumentSetupDefinition",
    "ExecutionProjectDefinition",
    "FileSetupContext",
    "FileSetupDefinition",
    "JsonValue",
    "ProjectSetupContext",
    "ProjectSetupDefinition",
    "ProjectTeardownContext",
    "ResolvedExecutionProject",
    "TestFileSelection",
    "TestTagSelection",
    "WorkflowExecutionProject",
]
