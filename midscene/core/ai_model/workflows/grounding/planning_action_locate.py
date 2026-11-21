"""Planning-based tap locator (upstream workflows/grounding/planning-action-locate.ts)."""

from typing import Any, Callable, Dict, List, Optional, TypedDict

from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.model_adapter.image_preprocess import (
    prepare_model_image,
)
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    user_prompt_to_string,
)


class PlanningTapLocatorDefinition(TypedDict, total=False):
    """Resolved planning tap locator callbacks."""

    build_system_prompt: Callable[[], str]
    parse_response: Callable[[str], Dict[str, Any]]
    transform_actions: Callable[
        [Dict[str, Any], Any, Dict[str, Any], Dict[str, int]],
        List[Dict[str, Any]],
    ]
    get_located_pixel_result: Callable[
        [List[Dict[str, Any]]], Optional[Dict[str, Any]]
    ]
    reasoning_content: Callable[[Dict[str, Any]], str]


async def run_planning_action_locate(
    definition: PlanningTapLocatorDefinition,
    target_element_description: Any,
    locate_image: Dict[str, Any],
    model_runtime: Any,
) -> Dict[str, Any]:
    """Run one planning pass and turn its actions into a pixel locate result."""
    shot_size = {
        "width": locate_image["width"],
        "height": locate_image["height"],
    }
    prepared = prepare_model_image(
        ensure_data_url(locate_image["imageBase64"]),
        shot_size["width"],
        shot_size["height"],
        None,
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"{definition['build_system_prompt']()}Tap: "
                f"{user_prompt_to_string(target_element_description)}"
            ),
        },
        {
            "role": "user",
            "content": [{"type": "image", "url": prepared["image_base64"]}],
        },
    ]
    try:
        response = await call_ai_with_string_response(messages, model_runtime)
        parsed = definition["parse_response"](response["content"])
        actions: List[Dict[str, Any]] = definition["transform_actions"](
            parsed, model_runtime, prepared, shot_size
        )
        located = definition["get_located_pixel_result"](actions)
        if not located:
            raise ValueError("No locatedPixelResult found in planner response")
        reasoning = definition.get("reasoning_content")
        return {
            "locatedPixelResult": located,
            "raw_response": response["content"],
            "usage": response.get("usage"),
            "reasoningContent": (
                reasoning(parsed) if reasoning else parsed.get("log", "")
            ),
        }
    except AIResponseParseError as error:
        return {
            "raw_response": error.raw_response,
            "usage": error.usage,
            "errors": [
                error.message
                or "Failed to parse planning tap locator response"
            ],
        }
    except Exception as error:
        return {
            "raw_response": str(error),
            "errors": [
                str(error) or "Failed to parse planning tap locator response"
            ],
        }


__all__ = ["PlanningTapLocatorDefinition", "run_planning_action_locate"]
