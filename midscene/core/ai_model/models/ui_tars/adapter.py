"""UI-TARS adapter (upstream ai-model/models/ui-tars/adapter.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
)
from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_value,
    unwrap_coordinate_list_like_input,
)


def _build_ui_tars_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    return config


UI_TARS_BBOX_COORDS = {
    "shape": "bbox",
    "order": "xy",
    "normalizedBy": 1000,
    "rounding": "round",
}


UI_TARS_POINT_COORDS = {
    "shape": "point",
    "order": "xy",
    "normalizedBy": 1000,
    "rounding": "round",
}


# UI-TARS has not received active updates for a long time, so this parser is
# intentionally kept separate from Doubao even though the current logic is the
# same. This avoids coupling UI-TARS behavior to future Doubao adapter changes.
def _parse_ui_tars_raw_locate_value(input_value: Any) -> dict[str, Any]:
    import re as _re

    bbox = unwrap_coordinate_list_like_input(input_value)
    if isinstance(bbox, str):
        if not _re.fullmatch(r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", bbox.strip()):
            raise ValueError(f"invalid bbox data string for ui-tars mode: {bbox}")
        return create_locate_result_value(
            UI_TARS_BBOX_COORDS, [float(p) for p in bbox.split()]
        )

    bbox_list: list[float] = []
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


def _create_ui_tars_adapter_config(model_version: str) -> dict[str, Any]:
    return {
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_ui_tars_params
            ),
        },
        "planning": {
            "kind": "custom",
            "cache_enabled": False,
            "default_replanning_cycle_limit": 40,
            "model_version": model_version,
        },
        "locate": {"element": {"result_format": UI_TARS_LOCATE_FORMAT}},
    }


ui_tars_adapters = {
    "vlm-ui-tars": _create_ui_tars_adapter_config("v1.0"),
    "vlm-ui-tars-doubao": _create_ui_tars_adapter_config("doubao-1.5-20b"),
    "vlm-ui-tars-doubao-1.5": _create_ui_tars_adapter_config("doubao-1.5-20b"),
}


__all__ = [
    "UI_TARS_BBOX_COORDS",
    "UI_TARS_LOCATE_FORMAT",
    "UI_TARS_POINT_COORDS",
    "_build_ui_tars_params",
    "_create_ui_tars_adapter_config",
    "_parse_ui_tars_raw_locate_value",
    "ui_tars_adapters",
]
