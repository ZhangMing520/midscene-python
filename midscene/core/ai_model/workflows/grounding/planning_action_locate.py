"""Planning-based tap locator (upstream workflows/grounding/planning-action-locate.ts)."""

from typing import Any, Callable, Dict, List, Optional, TypedDict

from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.model_adapter.image_preprocess import (
    prepare_model_image,
)
from midscene.core.ai_model.model_adapter.locate_prompt_order import (
    multimodal_prompt_to_messages,
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
    # Auto-GLM places its prompt in a system message and the screenshot in a
    # history entry, matching upstream buildCustomPlanningMessages.
    messages = [
        {
            "role": "system",
            "content": definition["build_system_prompt"](),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Tap: "
                        f"{user_prompt_to_string(target_element_description)}"
                    ),
                }
            ],
        },
        *multimodal_prompt_to_messages(target_element_description),
        {
            "type": "input-message",
            "message": {
                "role": "user",
                "content": [{"type": "image", "url": prepared["image_base64"]}],
            },
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


async def resolve_planning_tap_locator(
    definition: PlanningTapLocatorDefinition,
    planner: Dict[str, Any],
):
    """Build a locate function from a planning tap locator definition.

    Mirrors upstream ``resolvePlanningTapLocator``: the planner runs once with
    ``includeLocateInPlanning`` enabled and the definition extracts the pixel
    result from the produced actions.
    """

    async def locate(
        locate_request: Any = None,
        *,
        target_element_description: Any = None,
        locate_image: Optional[Dict[str, Any]] = None,
        model_runtime: Any = None,
    ) -> Dict[str, Any]:
        from types import SimpleNamespace

        from midscene.core.ai_model.model_adapter.planning import (
            resolve_custom_planning_definition,
        )
        from midscene.core.ai_model.workflows.planning.conversation_history import (
            ConversationHistory,
        )
        from midscene.core.ai_model.workflows.planning.custom_planning import (
            run_custom_planning,
        )

        if isinstance(locate_request, dict):
            target_element_description = locate_request.get(
                "targetElementDescription", target_element_description
            )
            locate_image = locate_request.get("locateImage", locate_image)
            options = locate_request.get("options") or {}
            model_runtime = options.get("modelRuntime", model_runtime)

        if not target_element_description:
            raise ValueError("cannot find the target element description")
        if locate_image is None or model_runtime is None:
            raise ValueError("planning tap locator requires a locate image and runtime")

        context = SimpleNamespace(
            screenshot_base64=locate_image["imageBase64"],
            size=SimpleNamespace(
                width=locate_image["width"], height=locate_image["height"]
            ),
        )
        planner_config = planner
        if "coordinate_normalizer" not in planner_config:
            planner_config = resolve_custom_planning_definition(planner_config)
        planner_config = {
            **planner_config,
            "messages": {
                **(planner_config.get("messages") or {}),
                "build_system_prompt": definition["build_system_prompt"],
                "build_user_instruction": lambda instruction: f"Tap: {instruction}",
            },
        }

        try:
            planning_response = await run_custom_planning(
                user_prompt_to_string(target_element_description),
                context,
                model_runtime,
                [{"name": "Tap", "locate_fields": ["locate"]}],
                ConversationHistory(),
                planner_config,
                include_locate_in_planning=True,
            )
            located_pixel_result = definition["get_located_pixel_result"](
                planning_response.get("actions") or []
            )
            if not located_pixel_result:
                raise ValueError("No locatedPixelResult found in planner response")
            return {
                "locatedPixelResult": located_pixel_result,
                "raw_response": planning_response.get("raw_response") or "",
                "usage": planning_response.get("usage"),
                "reasoningContent": planning_response.get("log") or "",
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

    return locate


__all__ = [
    "PlanningTapLocatorDefinition",
    "resolve_planning_tap_locator",
    "run_planning_action_locate",
]
