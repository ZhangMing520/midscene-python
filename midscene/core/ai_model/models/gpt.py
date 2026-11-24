"""GPT-5 / GPT-6 adapters (upstream ai-model/models/gpt.ts)."""

from collections.abc import Callable
from typing import Any

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
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
    build_responses_params_from_context,
)
from midscene.core.ai_model.models.utils.intent import is_locate_intent


def _resolve_gpt5_reasoning_effort(user_config: ReasoningInput) -> str | None:
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled == "default":
        return None
    if reasoning_enabled is True:
        return user_config.get("reasoningEffort") or "medium"
    return "none"


def _resolve_gpt6_reasoning_effort(user_config: ReasoningInput) -> str | None:
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled == "default":
        return None
    # Astra cannot disable reasoning; use its lowest effort when disabled.
    if reasoning_enabled is True:
        return user_config.get("reasoningEffort") or "medium"
    return "low"


def _build_gpt5_chat_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config.update(_json_object_config(user_config, expected_json_object_response))
    effort = _resolve_gpt5_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning_effort"] = effort
    return config


def _build_gpt6_chat_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    # GPT-6 does not support temperature; omit it from the serialized request.
    _apply_temperature(config, user_config, allow_override=False)
    config.update(_json_object_config(user_config, expected_json_object_response))
    effort = _resolve_gpt6_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning_effort"] = effort
    return config


def _build_gpt5_responses_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        config["text"] = {"format": {"type": "json_object"}}
    effort = _resolve_gpt5_reasoning_effort(user_config)
    if effort is not None:
        # Use current-turn reasoning only.
        config["reasoning"] = {"effort": effort, "context": "current_turn"}
    return config


def _build_gpt6_responses_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
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


def _resolve_gpt_image_detail(input_data: dict[str, Any]) -> str:
    if is_locate_intent(input_data.get("intent")) or input_data.get(
        "requiresOriginalImageDetail"
    ):
        return "original"
    return input_data.get("imageDetail") or "high"


def _build_gpt_codex_params(
    disabled_effort: str,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def build(input_data: dict[str, Any]) -> dict[str, Any]:
        effort = (
            _resolve_gpt5_reasoning_effort(input_data.get("userConfig") or {})
            if disabled_effort == "none"
            else _resolve_gpt6_reasoning_effort(input_data.get("userConfig") or {})
        )
        return {"config": {"effort": effort}}

    return build


def _create_gpt_adapter_config(family: str) -> dict[str, Any]:
    is_gpt6 = family == "gpt-6"
    return {
        "supported_protocols": ["openai-chat", "openai-responses"],
        "resolve_image_detail": _resolve_gpt_image_detail,
        "responses": {
            "replay_raw_assistant_output": False,
            "build_responses_params": build_responses_params_from_context(
                _build_gpt6_responses_params
                if is_gpt6
                else _build_gpt5_responses_params
            ),
        },
        "build_codex_app_server_params": _build_gpt_codex_params(
            "low" if is_gpt6 else "none"
        ),
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_gpt6_chat_params if is_gpt6 else _build_gpt5_chat_params
            ),
        },
        "locate": {
            "element": {
                "result_format": GPT_LOCATE_FORMAT,
            },
        },
    }


gpt_adapters = {
    "gpt-5": _create_gpt_adapter_config("gpt-5"),
    "gpt-6": _create_gpt_adapter_config("gpt-6"),
}


__all__ = [
    "GPT_LOCATE_FORMAT",
    "_build_gpt5_chat_params",
    "_build_gpt5_responses_params",
    "_build_gpt6_chat_params",
    "_build_gpt6_responses_params",
    "_create_gpt_adapter_config",
    "gpt_adapters",
]
