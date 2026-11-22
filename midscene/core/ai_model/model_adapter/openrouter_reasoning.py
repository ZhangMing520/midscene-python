"""OpenRouter unified reasoning params (upstream ai-model/model-adapter/openrouter-reasoning.ts)."""

from typing import Any, Dict, Optional, Union

from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)


def _reasoning_enabled(user_config: ModelRequestUserConfig) -> Union[bool, str]:
    reasoning_enabled = user_config.get("reasoningEnabled")
    return False if reasoning_enabled is None else reasoning_enabled


def build_open_router_reasoning_params(
    user_config: ModelRequestUserConfig,
    control_method: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """OpenRouter unified reasoning control (openrouter-reasoning.ts)."""
    reasoning_enabled = _reasoning_enabled(user_config)
    if reasoning_enabled == "default":
        return {}

    reasoning: Dict[str, Any] = {}
    if control_method and control_method.get("type") == "effort":
        if reasoning_enabled is True:
            reasoning["effort"] = (
                user_config.get("reasoningEffort")
                or control_method["defaultEnabledEffort"]
            )
        else:
            reasoning["effort"] = control_method["disabledEffort"]
    else:
        reasoning["enabled"] = bool(reasoning_enabled)
        if reasoning_enabled is True and user_config.get("reasoningEffort") is not None:
            reasoning["effort"] = user_config["reasoningEffort"]

    # Budget forwarding is independent of the reasoning control method.
    if reasoning_enabled is True and user_config.get("reasoningBudget") is not None:
        reasoning["max_tokens"] = user_config["reasoningBudget"]

    return {"reasoning": reasoning}


# Backward-compatible private alias used across the model adapters.
_build_openrouter_reasoning_params = build_open_router_reasoning_params


__all__ = [
    "_build_openrouter_reasoning_params",
    "_reasoning_enabled",
    "build_open_router_reasoning_params",
]
