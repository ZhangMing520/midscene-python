"""Agent tool types shared by CLI and Skill surfaces.

Upstream declares Zod schemas; the Python port uses plain field descriptors
(``{"type": "string", "description": "...", "optional": True}``) so the
framework has no runtime dependency on a schema library.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

# Default timeout constants for app loading verification.
DEFAULT_APP_LOADING_TIMEOUT_MS = 10000
DEFAULT_APP_LOADING_CHECK_INTERVAL_MS = 2000

ToolSchema = Dict[str, Dict[str, Any]]
ToolCliOption = Dict[str, Any]
ToolCliMetadata = Dict[str, Any]
ToolDefaults = Dict[str, Dict[str, Any]]


class ToolResult:
    """Result of one tool execution."""

    def __init__(
        self,
        content: Optional[List[Dict[str, Any]]] = None,
        is_error: bool = False,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.content = content or []
        self.is_error = is_error
        self._meta = meta

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"content": self.content}
        if self.is_error:
            payload["isError"] = True
        if self._meta is not None:
            payload["_meta"] = self._meta
        return payload


ToolHandler = Callable[[Dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class ToolDefinition:
    """Tool definition for Midscene CLI and Skill surfaces."""

    name: str
    description: str
    schema: ToolSchema
    handler: ToolHandler
    cli: Optional[ToolCliMetadata] = None


# Structural placeholders. Platform agents/devices are duck-typed in Python.
BaseAgent = Any
BaseDevice = Any
BaseUIObservation = Any
BaseUIObserver = Any


@dataclass
class ActionSpaceItem:
    """One entry of an action space, mirroring a DeviceAction."""

    name: str
    description: str = ""
    param_schema: ToolSchema = field(default_factory=dict)
    locate_fields: List[str] = field(default_factory=list)
    sample: Optional[Dict[str, Any]] = None
    interface_alias: Optional[str] = None


class UIObservationFrame(TypedDict):
    """A single frame in a portable UI observation record."""

    path: str
    mimeType: str
    capturedAt: int


class UIObservationRecord(TypedDict):
    """Serializable observation window persisted as a JSON manifest."""

    type: str
    version: int
    startedAt: float
    endedAt: float
    frames: List[UIObservationFrame]
    shotSize: Dict[str, float]
    shrunkShotToLogicalRatio: float


def schema_field(
    type_name: str = "any",
    description: str = "",
    optional: bool = False,
    enum: Optional[List[Any]] = None,
    items: Optional[Dict[str, Any]] = None,
    value: Any = None,
) -> Dict[str, Any]:
    """Build a plain schema field descriptor (small stand-in for ``z.*``)."""
    result: Dict[str, Any] = {"type": type_name}
    if description:
        result["description"] = description
    if optional:
        result["optional"] = True
    if enum is not None:
        result["enum"] = enum
    if items is not None:
        result["items"] = items
    if value is not None:
        result["value"] = value
    return result


__all__ = [
    "ActionSpaceItem",
    "BaseAgent",
    "BaseDevice",
    "BaseUIObservation",
    "BaseUIObserver",
    "DEFAULT_APP_LOADING_CHECK_INTERVAL_MS",
    "DEFAULT_APP_LOADING_TIMEOUT_MS",
    "ToolCliMetadata",
    "ToolCliOption",
    "ToolDefaults",
    "ToolDefinition",
    "ToolHandler",
    "ToolResult",
    "ToolSchema",
    "UIObservationFrame",
    "UIObservationRecord",
    "schema_field",
]
