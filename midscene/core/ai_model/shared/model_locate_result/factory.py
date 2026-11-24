"""Locate result codec factory (upstream shared/model-locate-result/factory.ts)."""

from typing import Any

from midscene.core.ai_model.shared.model_locate_result.coordinates import (
    resolve_bounds_type,
    resolve_locate_result_coordinates,
)
from midscene.core.ai_model.shared.model_locate_result.parse import (
    parse_numeric_locate_result,
)
from midscene.core.ai_model.shared.model_locate_result.pixel_mapper import (
    clamp_pixel_bbox_to_size,
    clamp_pixel_point_to_size,
    map_locate_result_to_pixel_bbox,
    map_locate_result_to_pixel_point,
    pixel_bbox_to_rect,
)
from midscene.core.ai_model.shared.model_locate_result.prompt_spec import (
    create_locate_result_prompt_spec,
)
from midscene.core.ai_model.shared.model_locate_result.validation import (
    assert_locate_result_coordinate_range_and_order,
    assert_locate_result_structure,
)


class LocateResultCodec:
    """Parse a raw locate value once and map it to {center, rect} pixels."""

    def __init__(
        self,
        prompt_spec: dict[str, Any],
        resolved_coordinates: dict[str, Any],
        parse_raw_locate_value=None,
    ):
        self.prompt_spec = prompt_spec
        self._resolved_coordinates = resolved_coordinates
        self._parse_raw_locate_value = parse_raw_locate_value or (
            lambda raw: parse_numeric_locate_result(resolved_coordinates, raw)
        )

    def to_pixel_result(
        self,
        raw_result: Any,
        context: dict[str, dict[str, float]],
    ) -> dict[str, Any]:
        """Return {center, rect?}; rect is None for point results."""
        result = self._parse_raw_locate_value(raw_result)
        prepared_size = context["preparedSize"]
        content_size = context.get("contentSize") or prepared_size
        assert_locate_result_structure(result)
        edge_bounds = (
            result["coordinatesMeta"]["shape"] == "bbox"
            and resolve_bounds_type(result["coordinatesMeta"].get("boundsType"))
            == "left-closed-right-open"
        )
        assert_locate_result_coordinate_range_and_order(
            result,
            prepared_size["width"] - (0 if edge_bounds else 1),
            prepared_size["height"] - (0 if edge_bounds else 1),
        )
        center = clamp_pixel_point_to_size(
            map_locate_result_to_pixel_point(result, prepared_size), content_size
        )
        rect: dict[str, float] | None = None
        if result["coordinatesMeta"]["shape"] == "bbox":
            bounds_type = resolve_bounds_type(
                result["coordinatesMeta"].get("boundsType")
            )
            pixel_bbox = clamp_pixel_bbox_to_size(
                map_locate_result_to_pixel_bbox(result, prepared_size),
                content_size,
                bounds_type,
            )
            rect = pixel_bbox_to_rect(pixel_bbox, bounds_type)
        return {"center": center, "rect": rect}


def create_locate_result_codec(
    result_format: dict[str, Any],
) -> LocateResultCodec:
    """Create a codec from a LocateResultFormatDefinition:
    {resultKey?, resultKeyAliases?, coordinates, parseRawLocateValue?}."""
    resolved = resolve_locate_result_coordinates(result_format["coordinates"])
    prompt_spec = create_locate_result_prompt_spec(
        resolved,
        result_key=result_format.get("resultKey"),
        result_key_aliases=result_format.get("resultKeyAliases"),
    )
    return LocateResultCodec(
        prompt_spec=prompt_spec,
        resolved_coordinates=resolved,
        parse_raw_locate_value=result_format.get("parseRawLocateValue"),
    )
