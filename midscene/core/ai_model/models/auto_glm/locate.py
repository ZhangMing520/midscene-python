"""AutoGLM planning-tap locator (upstream ai-model/models/auto-glm/locate.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.custom_planning_action import (
    get_tap_located_pixel_result,
    normalize_custom_locate_fields,
)
from midscene.core.ai_model.models.auto_glm.actions import transform_auto_glm_action
from midscene.core.ai_model.models.auto_glm.parser import (
    parse_auto_glm_planning_response,
)
from midscene.core.ai_model.models.auto_glm.planning import (
    AUTO_GLM_COORDINATES,
    _coordinate_distance_to_pixels_for,
)
from midscene.core.ai_model.models.auto_glm.prompt import (
    get_auto_glm_chinese_locate_prompt,
    get_auto_glm_multilingual_locate_prompt,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    prepare_model_image,
    user_prompt_to_string,
)


def create_auto_glm_planning_tap_locator(is_multilingual: bool) -> Dict[str, Any]:
    return {
        "build_system_prompt": (
            get_auto_glm_multilingual_locate_prompt
            if is_multilingual
            else get_auto_glm_chinese_locate_prompt
        ),
        "get_located_pixel_result": get_tap_located_pixel_result,
    }


async def auto_glm_locate(
    target_element_description: Any,
    locate_image: Dict[str, Any],
    model_runtime: Any,
) -> Dict[str, Any]:
    """Auto-GLM planning-tap-locator (models/auto-glm/locate.ts)."""
    from midscene.core.ai_model.service_caller.call_ai import (
        call_ai_with_string_response,
    )

    is_multilingual = model_runtime.adapter.family == "auto-glm-multilingual"
    locator = create_auto_glm_planning_tap_locator(is_multilingual)

    shot_size = {"width": locate_image["width"], "height": locate_image["height"]}
    prepared = prepare_model_image(
        ensure_data_url(locate_image["imageBase64"]),
        shot_size["width"],
        shot_size["height"],
        None,
    )
    messages = [
        {
            "role": "user",
            "content": f"{locator['build_system_prompt']()}Tap: {user_prompt_to_string(target_element_description)}",
        },
        {
            "role": "user",
            "content": [{"type": "image", "url": prepared["image_base64"]}],
        },
    ]
    try:
        response = await call_ai_with_string_response(messages, model_runtime)
        parsed = parse_auto_glm_planning_response(response["content"])
        actions = transform_auto_glm_action(
            parsed["action"],
            [],
            _coordinate_distance_to_pixels_for(
                {"shotSize": shot_size}, model_runtime, AUTO_GLM_COORDINATES
            ),
        )
        normalize_custom_locate_fields(
            actions,
            AUTO_GLM_COORDINATES,
            {
                "preparedSize": prepared["prepared_size"],
                "contentSize": prepared["content_size"],
            },
        )
        located = locator["get_located_pixel_result"](actions)
        if not located:
            raise ValueError("No locatedPixelResult found in planner response")
        return {
            "locatedPixelResult": located,
            "raw_response": response["content"],
            "usage": response.get("usage"),
            "reasoningContent": parsed["response"]["think"],
        }
    except AIResponseParseError as error:
        return {
            "raw_response": error.raw_response,
            "usage": error.usage,
            "errors": [error.message or "Failed to parse planning tap locator response"],
        }
    except Exception as error:
        return {
            "raw_response": str(error),
            "errors": [str(error) or "Failed to parse planning tap locator response"],
        }


__all__ = ["auto_glm_locate", "create_auto_glm_planning_tap_locator"]
