"""Kimi / Kimi K3 adapters (upstream ai-model/models/kimi.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_value,
    parse_coordinate_list,
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

def _build_kimi_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    # Kimi disallows custom temperature.
    _apply_temperature(config, user_config, allow_override=False)
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = _reasoning_enabled(user_config)
    if _is_openrouter(user_config.get("baseURL")):
        config.update(_build_openrouter_reasoning_params(user_config))
    elif reasoning_enabled != "default":
        config["thinking"] = {
            "type": "enabled" if reasoning_enabled is True else "disabled"
        }
    return config


def _build_kimi3_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    # Kimi disallows custom temperature.
    _apply_temperature(config, user_config, allow_override=False)
    config.update(_json_object_config(user_config, expected_json_object_response))
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


KIMI_NORMALIZED_POINT_COORDS = {
    "shape": "point", "order": "xy", "normalizedBy": 1, "rounding": "round",
}


KIMI_PIXEL_POINT_COORDS = {
    "shape": "point", "order": "xy", "rounding": "round",
}


def _parse_kimi_raw_locate_value(input_value: Any) -> Dict[str, Any]:
    point = parse_coordinate_list(input_value, "point")
    if len(point) != 2:
        raise ValueError(f"invalid point data: {input_value!r} ")
    x, y = point
    # Compatible with OSWorld's Kimi adapter: values <= 1 are normalized
    # coordinates, otherwise screenshot pixels.
    coordinates_meta = (
        KIMI_NORMALIZED_POINT_COORDS if x <= 1 and y <= 1 else KIMI_PIXEL_POINT_COORDS
    )
    return create_locate_result_value(coordinates_meta, [x, y])


KIMI_LOCATE_FORMAT = {
    "resultKey": "point",
    "coordinates": KIMI_NORMALIZED_POINT_COORDS,
    "parseRawLocateValue": _parse_kimi_raw_locate_value,
}
