"""Agent behavior init args (upstream agent-tools/agent-behavior-init-args.ts)."""

import json
from typing import Any

from midscene.shared.agent_tools.agent_context import is_agent_ai_context_key
from midscene.shared.agent_tools.types import ToolSchema, schema_field

AGENT_BEHAVIOR_INIT_ARG_SHAPE: ToolSchema = {
    "aiContexts": schema_field(
        "object",
        "Additional AI guidance such as business facts, rules, constraints, or "
        "output requirements. aiContexts.default is used only when neither the "
        "call nor its API key provides a context. Values override rather than "
        "automatically merge.",
        optional=True,
    ),
    "aiActContext": schema_field(
        "string",
        "Deprecated compatibility alias for aiContexts.aiAct. "
        "aiContexts.aiAct takes precedence when both are provided.",
        optional=True,
    ),
    "replanningCycleLimit": schema_field(
        "integer",
        "Maximum number of replanning cycles for aiAct. Default: model adapter "
        "default.",
        optional=True,
    ),
    "waitAfterAction": schema_field(
        "number",
        "Wait time in milliseconds after each action execution. Default: 300ms.",
        optional=True,
    ),
    "screenshotShrinkFactor": schema_field(
        "number",
        "Screenshot shrink factor before sending images to AI. Default: 1; high "
        "values may reduce recognition quality, especially on mobile.",
        optional=True,
    ),
}


def extract_agent_behavior_init_args(
    extracted: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not extracted:
        return None

    ai_contexts = {
        key: value
        for key, value in (extracted.get("aiContexts") or {}).items()
        if is_agent_ai_context_key(key) and isinstance(value, str)
    }

    agent_options: dict[str, Any] = {}
    if ai_contexts:
        agent_options["aiContexts"] = ai_contexts
    if isinstance(extracted.get("aiActContext"), str):
        agent_options["aiActContext"] = extracted["aiActContext"]
    if isinstance(extracted.get("aiActionContext"), str):
        agent_options["aiActionContext"] = extracted["aiActionContext"]
    for key in ("replanningCycleLimit", "waitAfterAction", "screenshotShrinkFactor"):
        if isinstance(extracted.get(key), (int, float)) and not isinstance(
            extracted.get(key), bool
        ):
            agent_options[key] = extracted[key]

    return agent_options or None


def _stable_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable_json_value(value[key]) for key in sorted(value)}
    return value


def get_agent_init_args_signature(
    init_args: dict[str, Any] | None,
) -> str | None:
    if not init_args:
        return None
    return json.dumps(_stable_json_value(init_args), ensure_ascii=False)


def should_rebuild_agent_for_init_args(
    current_signature: str | None, next_signature: str | None
) -> bool:
    return current_signature != next_signature and (
        current_signature is not None or next_signature is not None
    )


__all__ = [
    "AGENT_BEHAVIOR_INIT_ARG_SHAPE",
    "extract_agent_behavior_init_args",
    "get_agent_init_args_signature",
    "should_rebuild_agent_for_init_args",
]
