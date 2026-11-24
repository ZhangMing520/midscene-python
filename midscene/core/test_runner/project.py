"""Project and setup definition types (upstream test-runner/project.ts)."""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

JsonValue = Any


class TestFileSelection(TypedDict, total=False):
    include: list[str]
    exclude: list[str]


class TestTagSelection(TypedDict, total=False):
    include: list[str]
    exclude: list[str]


class ExecutionProjectDefinition(TypedDict, total=False):
    name: str
    setup: Any
    fileSetup: Any
    maxConcurrentFiles: int
    nodes: list[Any]
    files: TestFileSelection
    tags: TestTagSelection
    retry: int
    variables: dict[str, JsonValue]


class ResolvedExecutionProject(TypedDict, total=False):
    projectId: str
    name: str
    setup: Any
    fileSetup: Any
    maxConcurrentFiles: int
    files: TestFileSelection
    tags: dict[str, list[str]]
    retry: int
    variables: dict[str, JsonValue]


class WorkflowExecutionProject(TypedDict, total=False):
    """The document kernel does not consume selection rules or host setup."""

    projectId: str
    name: str
    retry: int


class ProjectSetupContext(TypedDict, total=False):
    project: ResolvedExecutionProject
    env: dict[str, str]
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
    file: dict[str, str]
    env: dict[str, str]
    signal: Any
    onTeardown: Callable[[Callable[[], Awaitable[None]]], None]


class FileSetupDefinition(TypedDict, total=False):
    name: str
    setup: Callable[[FileSetupContext], Awaitable[Any]]


class DocumentSetupContext(TypedDict, total=False):
    project: WorkflowExecutionProject
    projectContext: Any
    document: dict[str, Any]
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
