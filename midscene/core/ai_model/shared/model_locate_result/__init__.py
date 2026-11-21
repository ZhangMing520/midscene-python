"""Locate result parsing, validation and coordinate mapping.

Synced from upstream web-infra-dev/midscene v1.18.2:
  packages/core/src/ai-model/shared/model-locate-result/*
"""

from midscene.shared.env import (
    planning_model_family_required_for_locate_message,  # noqa: F401 (re-export)
)
from midscene.core.ai_model.shared.model_locate_result.coordinate_distance import (
    create_coordinate_distance_to_pixels,
)
from midscene.core.ai_model.shared.model_locate_result.coordinates import (
    BOUNDS_TYPE_ALIASES,
    NORMALIZATION_BASES,
    resolve_bounds_type,
    resolve_locate_result_coordinates,
    resolve_normalization_basis,
)
from midscene.core.ai_model.shared.model_locate_result.factory import (
    LocateResultCodec,
    create_locate_result_codec,
)
from midscene.core.ai_model.shared.model_locate_result.parse import (
    create_locate_result_value,
    parse_coordinate_list,
    parse_numeric_locate_result,
    unwrap_coordinate_list_like_input,
)
from midscene.core.ai_model.shared.model_locate_result.pixel_mapper import (
    clamp_pixel_bbox_to_size,
    clamp_pixel_point_to_size,
    map_locate_result_to_pixel_bbox,
    map_locate_result_to_pixel_point,
    max_pixel_coordinate,
    normalized_coordinate_to_pixel,
    pixel_bbox_to_rect,
    pixel_interval_center,
    pixel_interval_length,
    round_pixel_coordinate,
)
from midscene.core.ai_model.shared.model_locate_result.prompt_spec import (
    LOCATE_RESULT_EXAMPLE_REGIONS,
    create_locate_result_prompt_spec,
    describe_locate_result_coordinates,
    describe_locate_result_value_schema,
    format_locate_example_value,
    locate_result_example_value,
    locate_result_key,
    locate_result_name,
)
from midscene.core.ai_model.shared.model_locate_result.result_field import (
    locate_result_keys,
    read_locate_result_field,
)
from midscene.core.ai_model.shared.model_locate_result.types import (
    Bbox,
    BboxBoundsType,
    CoordinateRounding,
    LocateResultBbox,
    LocateResultPoint,
    LocateResultValue,
    NormalizationBasis,
    PixelBbox,
    RawLocateValue,
)
from midscene.core.ai_model.shared.model_locate_result.validation import (
    assert_locate_result_coordinate_range_and_order,
    assert_locate_result_structure,
)

__all__ = [
    "BOUNDS_TYPE_ALIASES",
    "NORMALIZATION_BASES",
    "LOCATE_RESULT_EXAMPLE_REGIONS",
    "Bbox",
    "BboxBoundsType",
    "CoordinateRounding",
    "LocateResultBbox",
    "LocateResultCodec",
    "LocateResultPoint",
    "LocateResultValue",
    "NormalizationBasis",
    "PixelBbox",
    "RawLocateValue",
    "assert_locate_result_coordinate_range_and_order",
    "assert_locate_result_structure",
    "clamp_pixel_bbox_to_size",
    "clamp_pixel_point_to_size",
    "create_coordinate_distance_to_pixels",
    "create_locate_result_codec",
    "create_locate_result_prompt_spec",
    "create_locate_result_value",
    "describe_locate_result_coordinates",
    "describe_locate_result_value_schema",
    "format_locate_example_value",
    "locate_result_example_value",
    "locate_result_key",
    "locate_result_keys",
    "locate_result_name",
    "map_locate_result_to_pixel_bbox",
    "map_locate_result_to_pixel_point",
    "max_pixel_coordinate",
    "normalized_coordinate_to_pixel",
    "parse_coordinate_list",
    "parse_numeric_locate_result",
    "pixel_bbox_to_rect",
    "pixel_interval_center",
    "pixel_interval_length",
    "read_locate_result_field",
    "resolve_bounds_type",
    "resolve_locate_result_coordinates",
    "resolve_normalization_basis",
    "round_pixel_coordinate",
    "unwrap_coordinate_list_like_input",
]
