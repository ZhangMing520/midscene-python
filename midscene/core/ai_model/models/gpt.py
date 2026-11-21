"""GPT-5 / GPT-6 adapters (upstream ai-model/models/gpt.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.model_adapter.chat_completion import (
    _json_object_config,
)
from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
    ReasoningInput,
)

def _resolve_gpt5_reasoning_effort(user_config: ReasoningInput) -> Optional[str]:
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled == "default":
        return None
    if reasoning_enabled is True:
        return user_config.get("reasoningEffort") or "medium"
    return "none"


def _resolve_gpt6_reasoning_effort(user_config: ReasoningInput) -> Optional[str]:
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled == "default":
        return None
    # Astra cannot disable reasoning; use its lowest effort when disabled.
    if reasoning_enabled is True:
        return user_config.get("reasoningEffort") or "medium"
    return "low"


def _build_gpt5_chat_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config.update(_json_object_config(user_config, expected_json_object_response))
    effort = _resolve_gpt5_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning_effort"] = effort
    return config


def _build_gpt6_chat_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    # GPT-6 does not support temperature; omit it from the serialized request.
    _apply_temperature(config, user_config, allow_override=False)
    config.update(_json_object_config(user_config, expected_json_object_response))
    effort = _resolve_gpt6_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning_effort"] = effort
    return config


def _build_gpt5_responses_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        config["text"] = {"format": {"type": "json_object"}}
    effort = _resolve_gpt5_reasoning_effort(user_config)
    if effort is not None:
        # Use current-turn reasoning only.
        config["reasoning"] = {"effort": effort, "context": "current_turn"}
    return config


def _build_gpt6_responses_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config, allow_override=False)
    effort = _resolve_gpt6_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning"] = {"effort": effort, "context": "current_turn"}
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        config["text"] = {"format": {"type": "json_object"}}
    return config


GPT_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {
        "shape": "bbox",
        "order": "xy",
        "boundsType": "left-closed-right-open",
        "rounding": "round",
    },
}
