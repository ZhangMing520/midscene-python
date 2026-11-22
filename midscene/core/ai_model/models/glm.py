"""GLM-V adapter (upstream ai-model/models/glm.ts)."""

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
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
)

def _build_glm_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = _reasoning_enabled(user_config)
    if _is_openrouter(user_config.get("baseURL")):
        config.update(_build_openrouter_reasoning_params(user_config))
    elif reasoning_enabled != "default":
        config["thinking"] = {
            "type": "enabled" if reasoning_enabled is True else "disabled"
        }
    return config


GLM_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "xy", "normalizedBy": 1000, "rounding": "round"},
}


glm_adapters = {
    "glm-v": {
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_glm_params
            ),
            "use_reasoning_as_content_fallback": True,
        },
        "locate": {
            "element": {
                "result_format": GLM_LOCATE_FORMAT,
            },
        },
    },
}


__all__ = ["GLM_LOCATE_FORMAT", "_build_glm_params", "glm_adapters"]
