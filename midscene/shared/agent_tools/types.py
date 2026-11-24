"""Agent tool types shared by CLI and Skill surfaces.

Upstream declares Zod schemas; the Python port uses plain field descriptors
(``{"type": "string", "description": "...", "optional": True}``) so the
framework has no runtime dependency on a schema library.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

# Default timeout constants for app loading verification.
DEFAULT_APP_LOADING_TIMEOUT_MS = 10000
DEFAULT_APP_LOADING_CHECK_INTERVAL_MS = 2000

ToolSchema = dict[str, dict[str, Any]]
ToolCliOption = dict[str, Any]
ToolCliMetadata = dict[str, Any]
ToolDefaults = dict[str, dict[str, Any]]


class ToolResult:
    """Result of one tool execution."""

    def __init__(
        self,
        content: list[dict[str, Any]] | None = None,
        is_error: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.content = content or []
        self.is_error = is_error
        self._meta = meta

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": self.content}
        if self.is_error:
            payload["isError"] = True
        if self._meta is not None:
            payload["_meta"] = self._meta
        return payload


ToolHandler = Callable[[dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class ToolDefinition:
    """Tool definition for Midscene CLI and Skill surfaces."""

    name: str
    description: str
    schema: ToolSchema
    handler: ToolHandler
    cli: ToolCliMetadata | None = None


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
    locate_fields: list[str] = field(default_factory=list)
    sample: dict[str, Any] | None = None
    interface_alias: str | None = None


class UIObservationFrame(TypedDict):
    """A single frame in a portable UI observation record."""

    path: str
    mimeType: str
    capturedAt: float


class UIObservationRecord(TypedDict):
    """Serializable observation window persisted as a JSON manifest."""

    type: str
    version: int
    startedAt: float
    endedAt: float
    frames: list[UIObservationFrame]
    shotSize: dict[str, float]
    shrunkShotToLogicalRatio: float


def schema_field(
    type_name: str = "any",
    description: str = "",
    optional: bool = False,
    enum: list[Any] | None = None,
    items: dict[str, Any] | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Build a plain schema field descriptor (small stand-in for ``z.*``)."""
    result: dict[str, Any] = {"type": type_name}
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
