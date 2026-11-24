"""Jev (System One) adapter config and callbacks (upstream ai-model/models/jev/adapter.ts)."""

from collections.abc import Callable
from typing import Any


def _jev_boolean_fn() -> Callable:
    from midscene.core.ai_model.models.jev.boolean import jev_boolean

    return jev_boolean


def _jev_locate_fn() -> Callable:
    from midscene.core.ai_model.models.jev.locate import jev_locate

    return jev_locate


def _jev_plan_fn() -> Callable:
    from midscene.core.ai_model.models.jev.planning import jev_plan

    return jev_plan


jev_adapters: dict[str, dict[str, Any]] = {
    "jev": {
        "model_type": "system-one",
        "allowed_task_types": ["locate", "boolean", "planning"],
        "supported_protocols": [],
        "locate": {"kind": "custom", "locate_fn": _jev_locate_fn},
        "insight": {"boolean_fn": _jev_boolean_fn},
        "planning": {
            "kind": "custom",
            "plan_fn": _jev_plan_fn,
            "cache_enabled": False,
            "supports_action_deep_locate": False,
            "default_replanning_cycle_limit": 20,
        },
    },
}


__all__ = [
    "_jev_boolean_fn",
    "_jev_locate_fn",
    "_jev_plan_fn",
    "jev_adapters",
]
