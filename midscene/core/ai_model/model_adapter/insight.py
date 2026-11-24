"""Insight adapter resolution (upstream model-adapter/insight.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict

from midscene.core.ai_model.model_adapter.default_insight_protocol import (
    create_default_insight_protocol,
)
from midscene.core.ai_model.model_adapter.insight_protocol import InsightProtocol

InsightProtocolDefinition = (
    InsightProtocol | Callable[[dict[str, Any]], InsightProtocol]
)


class InsightAdapter(TypedDict):
    boolean_fn: Callable[..., Any] | None
    protocol: InsightProtocol


_default_insight_protocol: InsightProtocol | None = None


def get_default_insight_protocol() -> InsightProtocol:
    """Return the shared default insight protocol (created once)."""
    global _default_insight_protocol
    if _default_insight_protocol is None:
        _default_insight_protocol = create_default_insight_protocol()
    return _default_insight_protocol


def resolve_insight_protocol(
    definition: InsightProtocolDefinition | None = None,
    context: dict[str, Any] | None = None,
) -> InsightProtocol:
    if definition is None:
        return get_default_insight_protocol()
    if callable(definition):
        return definition(context or {})
    return definition


def resolve_insight(
    adapter: Any,
    context: dict[str, Any] | None = None,
) -> InsightAdapter:
    """Resolve the boolean fast path and protocol for an adapter."""
    return {
        "boolean_fn": getattr(adapter, "insight_boolean_fn", None),
        "protocol": resolve_insight_protocol(
            getattr(adapter, "insight_protocol_definition", None), context
        ),
    }


__all__ = [
    "InsightAdapter",
    "InsightProtocolDefinition",
    "get_default_insight_protocol",
    "resolve_insight",
    "resolve_insight_protocol",
]
