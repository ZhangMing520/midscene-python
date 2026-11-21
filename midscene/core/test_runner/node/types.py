"""Workflow node types (upstream test-runner/node/types.ts)."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass
class NodeResult:
    """Human-readable summary plus structured step data."""

    summary: Optional[str] = None
    data: Any = None


@dataclass
class NodeReportTrace:
    type: str
    executionId: str
    metrics: Optional[Dict[str, Any]] = None


class NodeReportCollector:
    """Collects report references produced while a Step executes."""

    def __init__(self) -> None:
        self.traces: List[NodeReportTrace] = []
        self.snapshot_callbacks: List[Callable[..., Awaitable[Any]]] = []

    def add_trace(self, trace: NodeReportTrace) -> None:
        self.traces.append(trace)

    def on_snapshot(self, capture: Callable[..., Awaitable[Any]]) -> None:
        self.snapshot_callbacks.append(capture)


@dataclass
class NodeDefinition:
    name: str
    execute: Callable[..., Any]
    title: Optional[str] = None
    description: Optional[str] = None
    string_input_key: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None


@dataclass
class NodeExecutionContext:
    """Validated input plus per-step engine services."""

    input: Dict[str, Any]
    meta: Dict[str, Any]
    signal: Any
    context: Any
    on_teardown: Callable[[Callable[..., Any]], None]
    report: NodeReportCollector
    scope: str = "case"
    case: Optional[Dict[str, Any]] = None
    document: Optional[Dict[str, Any]] = None
