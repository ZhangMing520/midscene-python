"""AutoGLM adapter params (upstream ai-model/models/auto-glm/adapter.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)


def _build_auto_glm_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config["top_p"] = 0.85
    config["frequency_penalty"] = 0.2
    return config


__all__ = ["_build_auto_glm_params"]
