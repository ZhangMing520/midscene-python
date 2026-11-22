"""Distance-to-pixel conversion (upstream shared/model-locate-result/coordinate-distance.ts)."""

from typing import Any, Callable, Dict

from midscene.core.ai_model.shared.model_locate_result.pixel_mapper import (
    normalized_coordinate_to_pixel,
    round_pixel_coordinate,
)


def create_coordinate_distance_to_pixels(
    size: Dict[str, float], coordinate_system: Dict[str, Any]
) -> Callable[[float, str], float]:
    def distance_to_pixels(delta: float, axis: str) -> float:
        length = size["width"] if axis == "x" else size["height"]
        pixels = (
            abs(delta)
            if coordinate_system.get("normalizedBy") is None
            else normalized_coordinate_to_pixel(
                abs(delta),
                coordinate_system["normalizedBy"],
                length,
                coordinate_system.get("normalizationBasis", "image-size"),
            )
        )
        return round_pixel_coordinate(pixels, coordinate_system["rounding"])

    return distance_to_pixels
