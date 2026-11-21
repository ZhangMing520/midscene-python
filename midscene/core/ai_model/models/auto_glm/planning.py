"""AutoGLM custom planner (upstream ai-model/models/auto-glm/planning.ts)."""

from typing import Any, Callable, Dict

from midscene.core.ai_model.models.auto_glm.actions import transform_auto_glm_action
from midscene.core.ai_model.models.auto_glm.parser import (
    parse_auto_glm_planning_response,
)
from midscene.core.ai_model.models.auto_glm.prompt import (
    get_auto_glm_chinese_plan_prompt,
    get_auto_glm_multilingual_plan_prompt,
)
from midscene.core.ai_model.shared.model_locate_result import (
    create_coordinate_distance_to_pixels,
    resolve_locate_result_coordinates,
)
from midscene.core.ai_model.shared.multimodal_prompt import get_shot_size

from midscene.core.ai_model.model_adapter.custom_planning_types import (
    CustomPlanningDefinition,
)

AUTO_GLM_COORDINATES = {"shape": "point", "order": "xy", "normalizedBy": 1000}


def _coordinate_distance_to_pixels_for(
    context: Any, model_runtime: Any, coordinates: Dict[str, Any]
) -> Callable[[float, str], float]:
    size = get_shot_size(context)
    return create_coordinate_distance_to_pixels(
        size, resolve_locate_result_coordinates(coordinates)
    )


def create_auto_glm_planner(is_multilingual: bool) -> CustomPlanningDefinition:
    return {
        "messages": {
            "system_prompt_placement": "system-message",
            "build_system_prompt": (
                get_auto_glm_multilingual_plan_prompt
                if is_multilingual
                else get_auto_glm_chinese_plan_prompt
            ),
            "history_image_limit": 1,
            "build_assistant_content": lambda parsed, raw: (
                f"<think>{parsed['response']['think']}</think>"
                f"<answer>{parsed['response']['content']}</answer>"
            ),
        },
        "coordinates": AUTO_GLM_COORDINATES,
        "parse_response": lambda raw, context, runtime: parse_auto_glm_planning_response(raw),
        "transform_actions": lambda parsed, context, action_space, runtime: (
            transform_auto_glm_action(
                parsed["action"],
                action_space,
                _coordinate_distance_to_pixels_for(
                    context, runtime, AUTO_GLM_COORDINATES
                ),
            )
        ),
        "should_continue_planning": lambda parsed, actions: (
            parsed["action"]["_metadata"] != "finish"
        ),
        "build_response_log": lambda parsed, raw: raw,
    }


__all__ = ["AUTO_GLM_COORDINATES", "create_auto_glm_planner"]
