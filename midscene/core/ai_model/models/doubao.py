"""Doubao (Seed/Vision) adapter (upstream ai-model/models/doubao.ts)."""

from typing import Any, Dict, List

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
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
)

def _build_doubao_params(
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
            config["thinking"] = {
                "type": "enabled" if reasoning_enabled is True else "disabled"
            }
        if reasoning_enabled is True:
            reasoning_effort = user_config.get("reasoningEffort")
            if reasoning_effort is not None:
                config["reasoning_effort"] = reasoning_effort
    return config


DOUBAO_BBOX_COORDS = {
    "shape": "bbox", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}


DOUBAO_POINT_COORDS = {
    "shape": "point", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}


def _parse_doubao_raw_locate_value(input_value: Any) -> Dict[str, Any]:
    """Lenient Doubao parser: bbox lists of length 2-8 (upstream doubao.ts)."""
    import json as _json
    import re as _re

    bbox = unwrap_coordinate_list_like_input(input_value)
    bbox_list: List[float] = []
    if (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox)
    ):
        bbox_list = [float(v) for v in bbox]
    else:
        serialized = (
            input_value
            if isinstance(input_value, str)
            else _json.dumps(input_value, ensure_ascii=False)
        )
        sequences = [
            [int(x) for x in _re.findall(r"\d+", m)]
            for m in _re.findall(
                r"(?:^|[^a-zA-Z0-9])(\d+(?:[^a-zA-Z0-9]+\d+)+)(?=$|[^a-zA-Z0-9])",
                serialized,
            )
        ]
        if sequences:
            longest = max(len(s) for s in sequences)
            longest_sequences = [s for s in sequences if len(s) == longest]
            if len(longest_sequences) == 1:
                bbox_list = longest_sequences[0]

    if len(bbox_list) in (4, 5):
        return create_locate_result_value(DOUBAO_BBOX_COORDS, bbox_list[:4])
    if len(bbox_list) in (2, 3, 6, 7):
        return create_locate_result_value(DOUBAO_POINT_COORDS, bbox_list[:2])
    if len(bbox_list) == 8:
        return create_locate_result_value(
            DOUBAO_BBOX_COORDS,
            [bbox_list[0], bbox_list[1], bbox_list[4], bbox_list[5]],
        )
    raise ValueError(
        f"invalid bbox data for doubao-vision mode: {_json.dumps(input_value, ensure_ascii=False)} "
    )


DOUBAO_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "resultKeyAliases": ["bbox_2d"],
    "coordinates": DOUBAO_BBOX_COORDS,
    "parseRawLocateValue": _parse_doubao_raw_locate_value,
}


_doubao_vision_adapter_config: Dict[str, Any] = {
    "chat_completion": {
        "build_chat_completion_params": build_chat_completion_params_from_context(
            _build_doubao_params
        ),
        "use_reasoning_as_content_fallback": True,
    },
    "locate": {
        "element": {
            "result_format": DOUBAO_LOCATE_FORMAT,
        },
    },
}


doubao_adapters = {
    "doubao-vision": _doubao_vision_adapter_config,
    "doubao-seed": _doubao_vision_adapter_config,
}


__all__ = [
    "DOUBAO_BBOX_COORDS",
    "DOUBAO_LOCATE_FORMAT",
    "DOUBAO_POINT_COORDS",
    "_build_doubao_params",
    "_parse_doubao_raw_locate_value",
    "doubao_adapters",
]
