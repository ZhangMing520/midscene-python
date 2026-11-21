"""Jev locate workflow (upstream models/jev/locate.ts)."""

from typing import Any, Dict
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.system_one import SystemOneError, call_system_one
from midscene.core.ai_model.shared.model_locate_result import create_locate_result_codec

from midscene.core.ai_model.models.jev.image import (
    _prepare_jev_references,
    prepare_jev_image,
)

# Jev boxes are normalized 0-1 with half-open, image-edge semantics.
_jev_box_codec = create_locate_result_codec(
    {
        "coordinates": {
            "shape": "bbox",
            "normalizedBy": 1,
            "rounding": "none",
            "boundsType": "left-closed-right-open",
        }
    }
)


def map_jev_box(
    box: Dict[str, float], target_size: Dict[str, Any]
) -> Dict[str, Any]:
    """Map a normalized 0-1 Jev box to pixel {center, rect}."""
    return _jev_box_codec.to_pixel_result(
        [box["left"], box["top"], box["right"], box["bottom"]],
        {"preparedSize": target_size},
    )


async def jev_locate(
    target_element_description: Any,
    locate_image: Dict[str, Any],
    model_runtime: ModelRuntime,
) -> Dict[str, Any]:
    """Jev locate: returns {locatedPixelResult}, plus raw/usage."""
    image = prepare_jev_image(locate_image["imageBase64"])
    references = await _prepare_jev_references(target_element_description)
    target = (
        target_element_description
        if isinstance(target_element_description, str)
        else str(target_element_description.get("prompt", ""))
    )
    response = await call_system_one(
        model_runtime,
        {
            "state": {"target": target, "references": references["references"]},
            "images": {"screenshot": image, **references["images"]},
            "questions": {
                "target": {
                    "type": "box",
                    "instructions": (
                        "The single target described in `target`, in `screenshot`."
                    ),
                },
            },
        },
    )
    answers = response["answers"]
    if answers.get("target", {}).get("type") != "box":
        raise SystemOneError("Invalid Jev locate answer")

    return {
        "raw_response": response["content"],
        "usage": response["usage"],
        "locatedPixelResult": map_jev_box(
            answers["target"]["box"],
            {"width": locate_image["width"], "height": locate_image["height"]},
        ),
    }
