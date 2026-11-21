"""UI-TARS adapter (upstream ai-model/models/ui-tars/*)."""

from typing import Any, Dict, List

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_value,
    unwrap_coordinate_list_like_input,
)
from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

def _build_ui_tars_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    return config


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
