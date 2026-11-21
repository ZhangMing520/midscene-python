"""StepFun adapter (upstream ai-model/models/stepfun.ts)."""

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

def _build_step_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = _reasoning_enabled(user_config)
    if _is_openrouter(user_config.get("baseURL")):
        config.update(
            _build_openrouter_reasoning_params(
                user_config,
                {
                    "type": "effort",
                    "disabledEffort": "low",
                    "defaultEnabledEffort": "medium",
                },
            )
        )
    elif reasoning_enabled != "default":
        # Step reasoning models cannot disable thinking; use the lowest effort.
        config["reasoning_effort"] = (
            (user_config.get("reasoningEffort") or "medium")
            if reasoning_enabled is True
            else "low"
        )
    return config


STEP_LOCATE_FORMAT = {
    "resultKey": "point_2d",
    "resultKeyAliases": ["point"],
    "coordinates": {"shape": "point", "order": "xy", "normalizedBy": 1000},
}
