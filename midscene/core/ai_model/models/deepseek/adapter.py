"""DeepSeek adapter (upstream ai-model/models/deepseek/adapter.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.chat_completion import (
    _json_object_config,
)
from midscene.core.ai_model.model_adapter.is_openrouter import (
    _is_openrouter,
)
from midscene.core.ai_model.model_adapter.openrouter_reasoning import (
    _build_openrouter_reasoning_params,
    _reasoning_enabled,
)
from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)


def _build_deepseek_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    reasoning_enabled = _reasoning_enabled(user_config)
    is_thinking_mode = reasoning_enabled is True or reasoning_enabled == "default"
    # DeepSeek thinking mode does not support temperature; omit it.
    _apply_temperature(config, user_config, allow_override=not is_thinking_mode)
    config.update(_json_object_config(user_config, expected_json_object_response))
    if _is_openrouter(user_config.get("baseURL")):
        config.update(_build_openrouter_reasoning_params(user_config))
    else:
        if reasoning_enabled != "default":
            config["thinking"] = {
                "type": "enabled" if reasoning_enabled is True else "disabled"
            }
        if reasoning_enabled is True:
            reasoning_effort = user_config.get("reasoningEffort")
            if reasoning_effort is not None:
                config["reasoning_effort"] = reasoning_effort
    return config


__all__ = ["_build_deepseek_params"]
