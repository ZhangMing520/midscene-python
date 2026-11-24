"""Workflow node types (upstream test-runner/node/types.ts)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class NodeResult:
    """Human-readable summary plus structured step data."""

    summary: str | None = None
    data: Any = None


@dataclass
class NodeReportTrace:
    type: str
    executionId: str
    metrics: dict[str, Any] | None = None


class NodeReportCollector:
    """Collects report references produced while a Step executes."""

    def __init__(self) -> None:
        self.traces: list[NodeReportTrace] = []
        self.snapshot_callbacks: list[Callable[..., Awaitable[Any]]] = []

    def add_trace(self, trace: NodeReportTrace) -> None:
        self.traces.append(trace)

    def on_snapshot(self, capture: Callable[..., Awaitable[Any]]) -> None:
        self.snapshot_callbacks.append(capture)


@dataclass
class NodeDefinition:
    name: str
    execute: Callable[..., Any]
    title: str | None = None
    description: str | None = None
    string_input_key: str | None = None
    input_schema: dict[str, Any] | None = None


@dataclass
class NodeExecutionContext:
    """Validated input plus per-step engine services."""

    input: dict[str, Any]
    meta: dict[str, Any]
    signal: Any
    context: Any
    on_teardown: Callable[[Callable[..., Any]], None]
    report: NodeReportCollector
    scope: str = "case"
    case: dict[str, Any] | None = None
    document: dict[str, Any] | None = None
