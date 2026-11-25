"""Planning adapter resolution (upstream model-adapter/planning.ts)."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from midscene.core.ai_model.model_adapter.custom_planning_types import (
    CustomPlanningDefinition,
)
from midscene.core.ai_model.model_adapter.planning_protocol import (
    StandardPlanningProtocol,
)
from midscene.core.ai_model.shared.model_locate_result import (
    LocateResultCodec,
    create_locate_result_codec,
    resolve_locate_result_coordinates,
)
from midscene.core.ai_model.workflows.planning.types import PlanFn

DEFAULT_REPLANNING_CYCLE_LIMIT = 20


class ResolvedCustomPlanningDefinition(CustomPlanningDefinition, total=False):
    coordinate_system: dict[str, Any]
    coordinate_normalizer: LocateResultCodec


class PlanningAdapter(TypedDict, total=False):
    kind: str
    cache_enabled: bool
    default_replanning_cycle_limit: int
    supports_action_deep_locate: bool
    plan_fn: PlanFn | None
    protocol: StandardPlanningProtocol
    locate_result_codec: LocateResultCodec | None


def resolve_custom_planning_definition(
    config: CustomPlanningDefinition | dict[str, Any],
) -> ResolvedCustomPlanningDefinition:
    """Attach the resolved coordinate system and normalizer to a config."""
    coordinates = config.get("coordinates") or {}
    # Custom definitions intentionally retain extension keys; the known fields
    # are checked here while the definition remains an open runtime mapping.
    return cast(
        ResolvedCustomPlanningDefinition,
        {
            **config,
            "coordinate_system": resolve_locate_result_coordinates(coordinates),
            "coordinate_normalizer": create_locate_result_codec(
                {"coordinates": coordinates}
            ),
        },
    )


def resolve_planning(
    adapter: Any,
    protocol_context: dict[str, Any] | None = None,
) -> PlanningAdapter:
    """Resolve the custom or standard planning adapter for a model adapter."""
    cycle_limit = (
        adapter.replanning_cycle_limit
        if adapter.replanning_cycle_limit is not None
        else DEFAULT_REPLANNING_CYCLE_LIMIT
    )
    if adapter.planning_kind == "custom":
        return {
            "kind": "custom",
            "cache_enabled": adapter.cache_enabled,
            "default_replanning_cycle_limit": cycle_limit,
            "supports_action_deep_locate": adapter.supports_action_deep_locate,
            "plan_fn": adapter.planning_plan_fn,
        }

    protocol = adapter.planning_protocol
    if callable(protocol):
        protocol = protocol(protocol_context or {})
    return {
        "kind": "standard",
        "cache_enabled": adapter.cache_enabled,
        "default_replanning_cycle_limit": cycle_limit,
        "supports_action_deep_locate": adapter.supports_action_deep_locate,
        "protocol": protocol,
        "locate_result_codec": adapter.locate_result_codec,
    }


__all__ = [
    "DEFAULT_REPLANNING_CYCLE_LIMIT",
    "PlanningAdapter",
    "ResolvedCustomPlanningDefinition",
    "resolve_custom_planning_definition",
    "resolve_planning",
]
