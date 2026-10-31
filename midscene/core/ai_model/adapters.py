"""Model runtime and per-family adapter resolution.

Synced from upstream web-infra-dev/midscene v1.17.4:
  packages/core/src/ai-model/models/registry.ts
  packages/core/src/ai-model/models/default.ts
  packages/core/src/ai-model/models/{qwen,gpt,doubao,gemini,glm,kimi,mimo,deepseek}.ts
  packages/core/src/ai-model/models/{ui-tars,auto-glm,ant-ling,jev}/*
  packages/core/src/ai-model/models/model-fallback.ts
  packages/core/src/ai-model/models/deepseek/locate-protocol.ts
"""

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .locate_result import (
    create_locate_result_codec,
    create_locate_result_value,
    parse_coordinate_list,
    unwrap_coordinate_list_like_input,
)

ModelRequestUserConfig = Dict[str, Any]
ReasoningInput = Dict[str, Any]

MIDSCENE_DEFAULT_TEMPERATURE = 0.0

# ---------------------------------------------------------------------------
# Chat-completion parameter builders (per model family)
# ---------------------------------------------------------------------------


def _json_object_config(
    user_config: ModelRequestUserConfig, expected_json_object_response: bool
) -> Dict[str, Any]:
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        return {"response_format": {"type": "json_object"}}
    return {}


def _build_default_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    return config


def _build_qwen_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    # DashScope / vLLM thinking controls
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        config["enable_thinking"] = (
            bool(reasoning_enabled) if reasoning_enabled is not None else False
        )
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
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config["vl_high_resolution_images"] = True
    return config


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
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
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
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
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
    effort = _resolve_gpt6_reasoning_effort(user_config)
    if effort is not None:
        config["reasoning"] = {"effort": effort, "context": "current_turn"}
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        config["text"] = {"format": {"type": "json_object"}}
    return config


def _resolve_doubao_reasoning(user_config: ModelRequestUserConfig) -> Dict[str, Any]:
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled == "default":
        return {}
    thinking: Dict[str, Any] = {
        "type": "enabled" if reasoning_enabled else "disabled"
    }
    reasoning_budget = user_config.get("reasoningBudget")
    if reasoning_budget is not None:
        thinking["budget_tokens"] = reasoning_budget
    return {"thinking": thinking}


def _build_doubao_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        config.update(_resolve_doubao_reasoning(user_config))
        effort = user_config.get("reasoningEffort")
        if effort:
            config["reasoning_effort"] = effort
    return config


def _build_glm_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        config["thinking"] = {
            "type": "enabled" if reasoning_enabled else "disabled"
        }
    return config


def _build_gemini_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
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


def _build_kimi_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    # Kimi disallows custom temperature.
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = user_config.get("reasoningEnabled")
    config["thinking"] = {
        "type": "enabled" if (reasoning_enabled or False) else "disabled"
    }
    return config


def _build_kimi3_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    # Kimi disallows custom temperature.
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_effort = user_config.get("reasoningEffort")
    if reasoning_effort:
        config["reasoning_effort"] = reasoning_effort
    return config


def _build_mimo_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    config.update(_json_object_config(user_config, expected_json_object_response))
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    reasoning_enabled = user_config.get("reasoningEnabled")
    config["thinking"] = {
        "type": "enabled" if (reasoning_enabled or False) else "disabled"
    }
    return config


def _build_deepseek_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    reasoning_enabled = user_config.get("reasoningEnabled")
    is_thinking_mode = reasoning_enabled is True or reasoning_enabled == "default"
    # DeepSeek thinking mode does not support temperature; omit it.
    if not is_thinking_mode and user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config.update(_json_object_config(user_config, expected_json_object_response))
    if reasoning_enabled != "default":
        config["thinking"] = {
            "type": "enabled" if (reasoning_enabled or False) else "disabled"
        }
        reasoning_effort = user_config.get("reasoningEffort")
        if reasoning_effort:
            config["reasoning_effort"] = reasoning_effort
    return config


def _build_ant_ling_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config.update(_json_object_config(user_config, expected_json_object_response))
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        config["thinking"] = {
            "type": "enabled" if (reasoning_enabled or False) else "disabled"
        }
    return config


def _build_ui_tars_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    return config


def _build_auto_glm_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    if user_config.get("temperature") is not None:
        config["temperature"] = user_config["temperature"]
    config["top_p"] = 0.85
    config["frequency_penalty"] = 0.2
    return config


# ---------------------------------------------------------------------------
# Locate result formats (per model family)
# ---------------------------------------------------------------------------

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

DEFAULT_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {
        "shape": "bbox",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    },
}

GPT_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
}

GLM_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "xy", "normalizedBy": 1000, "rounding": "round"},
}

GEMINI_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "yx", "normalizedBy": 1000, "rounding": "round"},
}

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

UI_TARS_BBOX_COORDS = {
    "shape": "bbox", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}
UI_TARS_POINT_COORDS = {
    "shape": "point", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}


def _parse_ui_tars_raw_locate_value(input_value: Any) -> Dict[str, Any]:
    import re as _re

    bbox = unwrap_coordinate_list_like_input(input_value)
    if isinstance(bbox, str):
        if not _re.fullmatch(r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", bbox.strip()):
            raise ValueError(f"invalid bbox data string for ui-tars mode: {bbox}")
        return create_locate_result_value(
            UI_TARS_BBOX_COORDS, [float(p) for p in bbox.split()]
        )

    bbox_list: List[float] = []
    if isinstance(bbox, (list, tuple)) and bbox and isinstance(bbox[0], str):
        for item in bbox:
            if isinstance(item, str) and "," in item:
                x, y = item.split(",")
                bbox_list.extend([float(x.strip()), float(y.strip())])
            elif isinstance(item, str) and " " in item:
                x, y = item.split(" ")
                bbox_list.extend([float(x.strip()), float(y.strip())])
            else:
                bbox_list.append(float(item))
    else:
        bbox_list = [float(v) for v in bbox]

    if len(bbox_list) in (4, 5):
        return create_locate_result_value(UI_TARS_BBOX_COORDS, bbox_list[:4])
    if len(bbox_list) in (2, 3, 6, 7):
        return create_locate_result_value(UI_TARS_POINT_COORDS, bbox_list[:2])
    if len(bbox_list) == 8:
        return create_locate_result_value(
            UI_TARS_BBOX_COORDS,
            [bbox_list[0], bbox_list[1], bbox_list[4], bbox_list[5]],
        )
    raise ValueError(f"invalid bbox data for ui-tars mode: {input_value!r} ")


UI_TARS_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": UI_TARS_BBOX_COORDS,
    "parseRawLocateValue": _parse_ui_tars_raw_locate_value,
}

ANT_LING_LOCATE_FORMAT = {
    "resultKey": "point",
    "coordinates": {
        "shape": "point", "order": "xy", "normalizedBy": 1000, "rounding": "round"
    },
}

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

DEEPSEEK_POINT_COORDS = {
    "shape": "point", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}
DEEPSEEK_BBOX_COORDS = {
    "shape": "bbox", "order": "xy", "normalizedBy": 1000, "rounding": "round",
}


def _parse_deepseek_coordinate_values(
    input_value: Any, expected_length: int, label: str
) -> List[int]:
    import re as _re

    coordinate_texts = _re.findall(r"\d+", str(input_value))
    if len(coordinate_texts) != expected_length:
        raise ValueError(
            f"DeepSeek {label} locate result must contain exactly "
            f"{expected_length} positive integers, got {len(coordinate_texts)}"
        )
    return [int(t) for t in coordinate_texts]


def _parse_deepseek_point_locate_value(input_value: Any) -> Dict[str, Any]:
    return create_locate_result_value(
        DEEPSEEK_POINT_COORDS,
        _parse_deepseek_coordinate_values(input_value, 2, "point"),
    )


def _parse_deepseek_bbox_locate_value(input_value: Any) -> Dict[str, Any]:
    return create_locate_result_value(
        DEEPSEEK_BBOX_COORDS,
        _parse_deepseek_coordinate_values(input_value, 4, "bbox"),
    )


DEEPSEEK_ELEMENT_LOCATE_FORMAT = {
    "resultKey": "point",
    "coordinates": DEEPSEEK_POINT_COORDS,
    "parseRawLocateValue": _parse_deepseek_point_locate_value,
}

DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": DEEPSEEK_BBOX_COORDS,
    "parseRawLocateValue": _parse_deepseek_bbox_locate_value,
}


# ---------------------------------------------------------------------------
# DeepSeek locate protocols (models/deepseek/locate-protocol.ts)
# ---------------------------------------------------------------------------

_DEEPSEEK_REF_BOX_PATTERN = (
    r"<(?:｜｜|\|)ref(?:｜｜|\|)>\s*[\s\S]*?\s*<(?:｜｜|\|)/ref(?:｜｜|\|)>"
    r"\s*<(?:｜｜|\|)box(?:｜｜|\|)>\s*([\s\S]*?)\s*<(?:｜｜|\|)/box(?:｜｜|\|)>"
)
_DEEPSEEK_POINT_PATTERN = (
    r"^\s*<(?:｜｜|\|)point(?:｜｜|\|)>\s*([\s\S]*?)\s*<(?:｜｜|\|)/point(?:｜｜|\|)>\s*$"
)


def _deepseek_element_parse_raw_response(
    content: str, prompt_spec: Dict[str, Any]
) -> Dict[str, Any]:
    import re as _re

    match = _re.match(_DEEPSEEK_POINT_PATTERN, content)
    if not match:
        raise ValueError(
            "DeepSeek element locate response does not contain a valid "
            "<｜｜point｜｜>value<｜｜/point｜｜> result"
        )
    return {"kind": "located", "target": match.group(1)}


def _deepseek_search_area_parse_raw_response(
    content: str, prompt_spec: Dict[str, Any]
) -> Dict[str, Any]:
    import re as _re

    raw_boxes = _re.findall(_DEEPSEEK_REF_BOX_PATTERN, content)
    if not raw_boxes:
        raise ValueError(
            "DeepSeek search-area response does not contain a valid "
            "<｜｜ref｜｜>label<｜｜/ref｜｜><｜｜box｜｜>[[x1,y1,x2,y2]]<｜｜/box｜｜> result"
        )
    result: Dict[str, Any] = {"kind": "located", "target": raw_boxes[0]}
    if len(raw_boxes) > 1:
        result["references"] = list(raw_boxes[1:])
    return result


def _deepseek_element_response_instructions(prompt_spec: Dict[str, Any]) -> str:
    from .locate_result import format_locate_example_value

    return f"""## Output Format:
Return exactly one {prompt_spec['resultNoun']} using the following format, without any explanation or additional text:

<｜｜point｜｜>[{prompt_spec['resultValueSchema']}]<｜｜/point｜｜>

For example:
<｜｜point｜｜>[{format_locate_example_value(prompt_spec['exampleValues'][0])}]<｜｜/point｜｜>

Coordinate values must be integers.
Coordinate requirements: {prompt_spec['resultValueDescription']}
The origin is the top-left of the full screenshot."""


def _deepseek_search_area_response_instructions(prompt_spec: Dict[str, Any]) -> str:
    from .locate_result import format_locate_example_value

    target_example = format_locate_example_value(prompt_spec["exampleValues"][0])
    reference_example = format_locate_example_value(
        prompt_spec["exampleValues"][1]
        if len(prompt_spec["exampleValues"]) > 1
        else prompt_spec["exampleValues"][0]
    )
    return f"""## Objective:
- Identify the target UI element in the screenshot.
- Identify the reference elements that the description uses to select the target, such as an owner label, row value, column value, nearby text, or relative-position anchor.
- Return a tight {prompt_spec['resultNoun']} for the target first, followed by a tight {prompt_spec['resultNoun']} for each reference element.

## Reference Rules:
- If the description explicitly identifies the target through another visible element, you MUST return that visible element as a reference, even if the target appears unique.
- For descriptions like "B in the row whose A is X", B is the target and the visible X is a reference.
- For descriptions like "the icon next to label X", the icon is the target and the visible X is a reference.
- Do not return unrelated landmarks or alternative target candidates.

## Output Format:
Return one or more ref-box pairs using the following format, without any explanation or additional text:

<｜｜ref｜｜>target: concise target description<｜｜/ref｜｜><｜｜box｜｜>[{prompt_spec['resultValueSchema']}]<｜｜/box｜｜>
<｜｜ref｜｜>reference: concise reference description<｜｜/ref｜｜><｜｜box｜｜>[{prompt_spec['resultValueSchema']}]<｜｜/box｜｜>

For example:
If the request is "the edit icon in the row whose project name is Apollo", return:
<｜｜ref｜｜>target: edit icon<｜｜/ref｜｜><｜｜box｜｜>[{target_example}]<｜｜/box｜｜>
<｜｜ref｜｜>reference: Apollo<｜｜/ref｜｜><｜｜box｜｜>[{reference_example}]<｜｜/box｜｜>

The first ref-box pair must represent the target element. Every remaining pair must represent a reference element needed to identify the target. If no reference element is needed, return only the target pair. Each pair must contain exactly one {prompt_spec['resultNoun']}.
Coordinate values must be integers.
Coordinate requirements: {prompt_spec['resultValueDescription']}
The origin is the top-left of the full screenshot."""


DEEPSEEK_ELEMENT_LOCATE_PROTOCOL = {
    "system_prompt_introduction": (
        "## Role:\nYou are a GUI click grounding agent.\n\n## Objective:\n"
        "- Identify the UI element in the screenshot that matches the user's description.\n"
        "- Return the center point of that element."
    ),
    "build_response_instructions": _deepseek_element_response_instructions,
    "build_user_prompt": (
        lambda description: (
            "Locate the center point of the following UI element: " + description
        )
    ),
    "expected_json_object_response": False,
    "parse_raw_response": _deepseek_element_parse_raw_response,
}

DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL = {
    "system_prompt_introduction": "## Role:\nYou are a GUI grounding agent.",
    "build_response_instructions": _deepseek_search_area_response_instructions,
    "build_user_prompt": (
        lambda description: (
            "Locate the target and the reference elements needed to distinguish it: "
            + description
        )
    ),
    "expected_json_object_response": False,
    "parse_raw_response": _deepseek_search_area_parse_raw_response,
}


# ---------------------------------------------------------------------------
# Adapter definitions
# ---------------------------------------------------------------------------

_ALL_PROTOCOLS = ["openai-chat", "openai-responses"]


class ModelAdapter:
    """Resolved per-family adapter: chat-completion params + locate formats."""

    def __init__(
        self,
        family: str,
        build_chat_completion_params: Optional[Callable] = None,
        unsupported_user_config: Optional[List[str]] = None,
        use_reasoning_as_content_fallback: bool = False,
        reasoning_content_keys: Optional[List[str]] = None,
        locate_element_format: Optional[Dict[str, Any]] = None,
        image_pad_block_size: Optional[int] = None,
        supported_protocols: Optional[List[str]] = None,
        build_responses_params: Optional[Callable] = None,
        responses_unsupported_user_config: Optional[List[str]] = None,
        search_area_locate_format: Optional[Dict[str, Any]] = None,
        search_area_protocol: Optional[Dict[str, Any]] = None,
        element_protocol: Optional[Dict[str, Any]] = None,
        allowed_task_types: Optional[List[str]] = None,
        replanning_cycle_limit: Optional[int] = None,
        cache_enabled: bool = True,
        planning_kind: str = "standard",
        planning_plan_fn: Optional[Callable] = None,
        locate_kind: str = "standard",
        locate_fn: Optional[Callable] = None,
        replay_raw_assistant_message: bool = False,
        supports_action_deep_locate: Optional[bool] = None,
        insight_boolean_fn: Optional[Callable] = None,
    ):
        self.family = family
        self._build_params = build_chat_completion_params or _build_default_params
        self.unsupported_user_config = unsupported_user_config or []
        self.use_reasoning_as_content_fallback = use_reasoning_as_content_fallback
        self.reasoning_content_keys = reasoning_content_keys or ["reasoning_content"]
        self._locate_element_format = locate_element_format or DEFAULT_LOCATE_FORMAT
        self.image_pad_block_size = image_pad_block_size
        self.supported_protocols_list = supported_protocols or ["openai-chat"]
        self.build_responses_params = build_responses_params
        self.responses_unsupported_user_config = responses_unsupported_user_config or []
        self._search_area_locate_format = search_area_locate_format
        self._search_area_protocol = search_area_protocol
        self._element_protocol = element_protocol
        self.allowed_task_types = allowed_task_types  # None = all
        self.replanning_cycle_limit = replanning_cycle_limit
        self.cache_enabled = cache_enabled
        self.planning_kind = planning_kind
        self.planning_plan_fn = planning_plan_fn
        self.locate_kind = locate_kind
        self.locate_fn = locate_fn
        self.replay_raw_assistant_message = replay_raw_assistant_message
        self.supports_action_deep_locate = (
            supports_action_deep_locate
            if supports_action_deep_locate is not None
            else planning_kind == "standard"
        )
        self.insight_boolean_fn = insight_boolean_fn
        self._locate_codec: Optional[Any] = None
        self._locate_protocol: Optional[Any] = None
        self._planning_protocol: Optional[Any] = None

    def supports_protocol(self, protocol: str) -> bool:
        return protocol in self.supported_protocols_list

    def build_chat_completion_params(
        self,
        midscene_defaults: Dict[str, Any],
        user_config: ModelRequestUserConfig,
        expected_json_object_response: bool = False,
    ) -> Dict[str, Any]:
        merged_user_config = dict(user_config)
        for key in self.unsupported_user_config:
            merged_user_config.pop(key, None)
        return self._build_params(
            midscene_defaults, merged_user_config, expected_json_object_response
        )

    @property
    def locate_protocol(self):
        """Standard locate protocols: element + search-area (lazy import)."""
        if self._locate_protocol is None:
            from .protocols import (
                create_default_element_protocol,
                create_default_search_area_protocol,
            )

            self._locate_protocol = {
                "element": self._element_protocol
                or create_default_element_protocol(),
                "search_area": self._search_area_protocol
                or create_default_search_area_protocol(),
            }
        return self._locate_protocol

    @property
    def planning_protocol(self):
        """Standard Midscene XML planning protocol (lazy import)."""
        if self._planning_protocol is None:
            from .protocols import create_default_planning_protocol

            self._planning_protocol = create_default_planning_protocol()
        return self._planning_protocol

    @property
    def locate_result_codec(self):
        if self._locate_codec is None:
            self._locate_codec = create_locate_result_codec(
                self._locate_element_format
            )
        return self._locate_codec

    @property
    def search_area_result_codec(self):
        if self._search_area_locate_format is None:
            return self.locate_result_codec
        return create_locate_result_codec(self._search_area_locate_format)


def _default_adapter() -> ModelAdapter:
    # Default adapter recovers from empty content via reasoning_content because
    # many OpenAI-compatible servers emit useful output there.
    return ModelAdapter(
        family="default",
        unsupported_user_config=[
            "reasoningEnabled",
            "reasoningEffort",
            "reasoningBudget",
        ],
        use_reasoning_as_content_fallback=True,
    )


def _qwen3_adapter() -> ModelAdapter:
    return ModelAdapter(
        family="qwen3-vl",
        build_chat_completion_params=_build_qwen_params,
        unsupported_user_config=["reasoningEffort"],
        reasoning_content_keys=["reasoning_content", "reasoning"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=QWEN3_LOCATE_FORMAT,
    )


def _adapter_registry() -> Dict[str, ModelAdapter]:
    qwen3 = _qwen3_adapter()
    ui_tars_doubao = ModelAdapter(
        family="vlm-ui-tars-doubao",
        build_chat_completion_params=_build_ui_tars_params,
        unsupported_user_config=[
            "reasoningEnabled",
            "reasoningEffort",
            "reasoningBudget",
        ],
        locate_element_format=UI_TARS_LOCATE_FORMAT,
        replanning_cycle_limit=40,
        cache_enabled=False,
        planning_kind="custom",
    )
    deepseek = ModelAdapter(
        family="deepseek",
        build_chat_completion_params=_build_deepseek_params,
        unsupported_user_config=["reasoningBudget"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=DEEPSEEK_ELEMENT_LOCATE_FORMAT,
        element_protocol=DEEPSEEK_ELEMENT_LOCATE_PROTOCOL,
        search_area_locate_format=DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT,
        search_area_protocol=DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL,
    )
    gemini = ModelAdapter(
        family="gemini",
        build_chat_completion_params=_build_gemini_params,
        unsupported_user_config=["reasoningBudget"],
        locate_element_format=GEMINI_LOCATE_FORMAT,
    )
    doubao = ModelAdapter(
        family="doubao-seed",
        build_chat_completion_params=_build_doubao_params,
        unsupported_user_config=["reasoningBudget"],
        use_reasoning_as_content_fallback=True,
        locate_element_format=DOUBAO_LOCATE_FORMAT,
    )

    registry: Dict[str, ModelAdapter] = {
        "default": _default_adapter(),
        "qwen2.5-vl": ModelAdapter(
            family="qwen2.5-vl",
            build_chat_completion_params=_build_qwen25_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            locate_element_format=QWEN25_LOCATE_FORMAT,
            image_pad_block_size=28,
        ),
        "qwen3-vl": qwen3,
        "qwen3": qwen3,
        "qwen3.5": qwen3,
        "qwen3.6": qwen3,
        "gpt-5": ModelAdapter(
            family="gpt-5",
            build_chat_completion_params=_build_gpt5_chat_params,
            build_responses_params=_build_gpt5_responses_params,
            responses_unsupported_user_config=["reasoningBudget"],
            unsupported_user_config=["reasoningBudget"],
            supported_protocols=_ALL_PROTOCOLS,
            locate_element_format=GPT_LOCATE_FORMAT,
        ),
        "gpt-6": ModelAdapter(
            family="gpt-6",
            build_chat_completion_params=_build_gpt6_chat_params,
            build_responses_params=_build_gpt6_responses_params,
            responses_unsupported_user_config=["temperature", "reasoningBudget"],
            unsupported_user_config=["temperature", "reasoningBudget"],
            supported_protocols=_ALL_PROTOCOLS,
            locate_element_format=GPT_LOCATE_FORMAT,
        ),
        "doubao-seed": doubao,
        "doubao-vision": doubao,
        "gemini": gemini,
        "glm-v": ModelAdapter(
            family="glm-v",
            build_chat_completion_params=_build_glm_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=GLM_LOCATE_FORMAT,
        ),
        "kimi": ModelAdapter(
            family="kimi",
            build_chat_completion_params=_build_kimi_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=KIMI_LOCATE_FORMAT,
        ),
        "kimi3": ModelAdapter(
            family="kimi3",
            build_chat_completion_params=_build_kimi3_params,
            unsupported_user_config=["reasoningEnabled", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=KIMI_LOCATE_FORMAT,
            replay_raw_assistant_message=True,
        ),
        "xiaomi-mimo": ModelAdapter(
            family="xiaomi-mimo",
            build_chat_completion_params=_build_mimo_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            use_reasoning_as_content_fallback=True,
            locate_element_format=DEFAULT_LOCATE_FORMAT,
        ),
        "deepseek": deepseek,
        "ant-ling": ModelAdapter(
            family="ant-ling",
            build_chat_completion_params=_build_ant_ling_params,
            unsupported_user_config=["reasoningEffort", "reasoningBudget"],
            supported_protocols=["openai-chat"],
            locate_element_format=ANT_LING_LOCATE_FORMAT,
        ),
        "vlm-ui-tars": ModelAdapter(
            family="vlm-ui-tars",
            build_chat_completion_params=_build_ui_tars_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            locate_element_format=UI_TARS_LOCATE_FORMAT,
            replanning_cycle_limit=40,
            cache_enabled=False,
            planning_kind="custom",
        ),
        "vlm-ui-tars-doubao": ui_tars_doubao,
        "vlm-ui-tars-doubao-1.5": ui_tars_doubao,
        "auto-glm": ModelAdapter(
            family="auto-glm",
            build_chat_completion_params=_build_auto_glm_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            replanning_cycle_limit=100,
            cache_enabled=False,
            planning_kind="custom",
            locate_kind="custom",
        ),
        "auto-glm-multilingual": ModelAdapter(
            family="auto-glm-multilingual",
            build_chat_completion_params=_build_auto_glm_params,
            unsupported_user_config=[
                "reasoningEnabled",
                "reasoningEffort",
                "reasoningBudget",
            ],
            replanning_cycle_limit=100,
            cache_enabled=False,
            planning_kind="custom",
            locate_kind="custom",
        ),
        "jev": ModelAdapter(
            family="jev",
            allowed_task_types=["locate", "boolean", "planning"],
            supported_protocols=[],
            locate_kind="custom",
            planning_kind="custom",
            cache_enabled=False,
            replanning_cycle_limit=20,
            insight_boolean_fn=_jev_boolean_fn(),
        ),
    }
    return registry


_ADAPTER_CACHE: Dict[str, ModelAdapter] = {}
_REGISTRY: Optional[Dict[str, ModelAdapter]] = None


def _jev_boolean_fn() -> Callable:
    from .workflows.jev import jev_boolean

    return jev_boolean


def get_model_adapter(model_family: Optional[str] = None) -> ModelAdapter:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _adapter_registry()
        # Bind custom planners (UI-TARS / Auto-GLM) to their adapters on first use.
        from .workflows.planning_custom import register_custom_planners

        register_custom_planners()
    cache_key = model_family or "default"
    adapter = _ADAPTER_CACHE.get(cache_key)
    if adapter is not None:
        return adapter
    if model_family:
        adapter = _REGISTRY.get(model_family)
        if adapter is None:
            raise ValueError(
                f"No model adapter registered for modelFamily: {model_family}"
            )
    else:
        adapter = _REGISTRY["default"]
    _ADAPTER_CACHE[cache_key] = adapter
    return adapter


class ModelRuntime:
    """A model config bound to its family adapter (upstream ModelRuntime)."""

    def __init__(self, config: Dict[str, Any], adapter: Optional[ModelAdapter] = None):
        self.config = config
        self.adapter = adapter or get_model_adapter(config.get("modelFamily"))
        self.on_usage = None  # optional callback(AIUsageInfo)
        self.model_fallback: Optional[Dict[str, Any]] = None

    @property
    def model_family(self) -> Optional[str]:
        return self.config.get("modelFamily")

    @property
    def model_name(self) -> Optional[str]:
        return self.config.get("modelName")


def get_model_runtime(config: Dict[str, Any]) -> ModelRuntime:
    return ModelRuntime(
        config=config, adapter=get_model_adapter(config.get("modelFamily"))
    )


# ---------------------------------------------------------------------------
# Model fallback (models/model-fallback.ts)
# ---------------------------------------------------------------------------

def resolve_model_for_task_type(
    get_model_config: Callable[[str], Dict[str, Any]],
    intent: str,
    task_type: str,
) -> ModelRuntime:
    """Resolve the runtime for a task type, falling back to the default model
    when the requested slot's adapter cannot perform the task."""
    requested = get_model_runtime(get_model_config(intent))
    allowed = requested.adapter.allowed_task_types
    if allowed is None or task_type in allowed:
        return requested

    runtime = get_model_runtime({**get_model_config("default"), "intent": intent})
    default_allowed = runtime.adapter.allowed_task_types
    if default_allowed is not None and task_type not in default_allowed:
        raise ValueError(
            f"The default model cannot perform {task_type}. Configure a "
            "general-purpose default model."
        )
    reason = (
        f"{requested.config.get('modelFamily')} does not support {task_type}; "
        "using the default model"
    )
    logger.warning(reason)
    runtime.model_fallback = {
        "requestedModel": requested.config.get("modelName"),
        "requestedSlot": requested.config.get("slot"),
        "taskType": task_type,
        "reason": reason,
    }
    return runtime


# ---------------------------------------------------------------------------
# Intent helpers (models/utils/intent.ts)
# ---------------------------------------------------------------------------

def is_locate_intent(intent: Optional[str]) -> bool:
    return intent == "locate"
