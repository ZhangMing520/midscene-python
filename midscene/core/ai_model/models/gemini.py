"""Gemini adapter (upstream ai-model/models/gemini.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

def _build_gemini_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        # Google's native thinking_config; relays reject the minimal level.
        config["extra_body"] = {
            "google": {
                "thinking_config": {
                    "include_thoughts": True,
                    "thinking_level": (
                        user_config.get("reasoningEffort") or "medium"
                    )
                    if reasoning_enabled
                    else "low",
                }
            }
        }
    return config


GEMINI_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "yx", "normalizedBy": 1000, "rounding": "round"},
}
