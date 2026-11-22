"""Tencent Hunyuan adapter (upstream ai-model/models/tencent-hy.ts)."""

from typing import Any, Dict

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

def _build_tencent_hy_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    reasoning_enabled = _reasoning_enabled(user_config)
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


TENCENT_HY_LOCATE_FORMAT = {
    "resultKey": "box_2d",
    "coordinates": {"shape": "bbox", "order": "xy", "normalizedBy": 1000},
}


tencent_hy_adapters = {
    "tencent-hy": {
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_tencent_hy_params
            ),
        },
        "locate": {"element": {"result_format": TENCENT_HY_LOCATE_FORMAT}},
    },
}


__all__ = [
    "TENCENT_HY_LOCATE_FORMAT",
    "_build_tencent_hy_params",
    "tencent_hy_adapters",
]
