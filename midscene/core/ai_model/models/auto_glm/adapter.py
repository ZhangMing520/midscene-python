"""AutoGLM adapter params (upstream ai-model/models/auto-glm/adapter.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
)


def _build_auto_glm_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config["top_p"] = 0.85
    config["frequency_penalty"] = 0.2
    return config


def _create_auto_glm_adapter_config(is_multilingual: bool) -> dict[str, Any]:
    return {
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_auto_glm_params
            ),
        },
        "planning": {
            "kind": "custom",
            "cache_enabled": False,
            "default_replanning_cycle_limit": 100,
            "planner": {"multilingual": is_multilingual},
        },
        "locate": {
            "kind": "custom",
            "planning_tap_locator": {"multilingual": is_multilingual},
        },
    }


auto_glm_adapters = {
    "auto-glm": _create_auto_glm_adapter_config(False),
    "auto-glm-multilingual": _create_auto_glm_adapter_config(True),
}


__all__ = [
    "_build_auto_glm_params",
    "_create_auto_glm_adapter_config",
    "auto_glm_adapters",
]
