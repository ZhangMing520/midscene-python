"""Qwen 2.5 / 3-VL / 3 / 4 adapters (upstream ai-model/models/qwen.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_value,
    unwrap_coordinate_list_like_input,
)
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

def _build_qwen_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    """qwen3-vl: native thinking controls only, no OpenRouter branch."""
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    reasoning_enabled = _reasoning_enabled(user_config)
    if reasoning_enabled != "default":
        config["enable_thinking"] = bool(reasoning_enabled)
        if reasoning_enabled is True:
            reasoning_budget = user_config.get("reasoningBudget")
            if reasoning_budget is not None:
                config["thinking_budget"] = reasoning_budget
    return config


def _build_qwen3_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    """qwen3 / qwen3.5 / qwen3.6: native or OpenRouter reasoning controls."""
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    reasoning_enabled = _reasoning_enabled(user_config)
    if _is_openrouter(user_config.get("baseURL")):
        config.update(_build_openrouter_reasoning_params(user_config))
    else:
        if reasoning_enabled != "default":
            config["enable_thinking"] = bool(reasoning_enabled)
        if reasoning_enabled is True:
            reasoning_budget = user_config.get("reasoningBudget")
            if reasoning_budget is not None:
                config["thinking_budget"] = reasoning_budget
    return config


def _build_qwen4_params(
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
    else:
        if reasoning_enabled != "default":
            config["enable_thinking"] = bool(reasoning_enabled)
        if reasoning_enabled is True:
            reasoning_effort = user_config.get("reasoningEffort")
            if reasoning_effort is not None:
                config["reasoning_effort"] = reasoning_effort
            reasoning_budget = user_config.get("reasoningBudget")
            if reasoning_budget is not None:
                config["thinking_budget"] = reasoning_budget
    return config


def _build_qwen25_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    config["vl_high_resolution_images"] = True
    return config


def _parse_qwen25_raw_locate_value(input_value: Any) -> Dict[str, Any]:
    bbox = unwrap_coordinate_list_like_input(input_value)
    if len(bbox) < 2:
        raise ValueError(f"invalid bbox data for qwen-vl mode: {bbox!r} ")
    if (
        len(bbox) > 3
        and isinstance(bbox[2], (int, float))
        and isinstance(bbox[3], (int, float))
    ):
        return create_locate_result_value(
            {"shape": "bbox", "order": "xy", "rounding": "round"},
            [bbox[0], bbox[1], bbox[2], bbox[3]],
        )
    return create_locate_result_value(
        {"shape": "point", "order": "xy", "rounding": "round"},
        [bbox[0], bbox[1]],
    )


QWEN25_LOCATE_FORMAT = {
    "resultKey": "bbox_2d",
    "resultKeyAliases": ["bbox"],
    "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
    "parseRawLocateValue": _parse_qwen25_raw_locate_value,
}


QWEN3_LOCATE_FORMAT = {
    "resultKey": "bbox_2d",
    "resultKeyAliases": ["bbox"],
    "coordinates": {
        "shape": "bbox",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    },
}


QWEN4_LOCATE_FORMAT = {
    "resultKey": "point",
    "resultKeyAliases": ["point_2d"],
    "coordinates": {
        "shape": "point",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    },
}


def _parse_qwen_locate_json(raw: str, source: str = "generic-object") -> Any:
    """Unwrap Qwen3/Qwen4 single-item locate arrays: [{"bbox_2d": ...}]."""
    from midscene.core.ai_model.shared.json import parse_model_response_json

    parsed = parse_model_response_json(raw, source=source)
    if (
        source in ("locate", "section-locator")
        and isinstance(parsed, list)
        and len(parsed) == 1
        and isinstance(parsed[0], dict)
    ):
        return parsed[0]
    return parsed
