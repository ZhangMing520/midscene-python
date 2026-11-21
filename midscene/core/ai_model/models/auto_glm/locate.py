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
from midscene.core.ai_model.workflows.grounding.planning_action_locate import (
    PlanningTapLocatorDefinition,
    run_planning_action_locate,
)


def create_auto_glm_planning_tap_locator(
    is_multilingual: bool,
) -> PlanningTapLocatorDefinition:
    def transform_actions(
        parsed: Dict[str, Any],
        model_runtime: Any,
        prepared: Dict[str, Any],
        shot_size: Dict[str, int],
    ):
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
        return actions

    return {
        "build_system_prompt": (
            get_auto_glm_multilingual_locate_prompt
            if is_multilingual
            else get_auto_glm_chinese_locate_prompt
        ),
        "parse_response": parse_auto_glm_planning_response,
        "transform_actions": transform_actions,
        "get_located_pixel_result": get_tap_located_pixel_result,
        "reasoning_content": lambda parsed: parsed["response"]["think"],
    }


async def auto_glm_locate(
    target_element_description: Any,
    locate_image: Dict[str, Any],
    model_runtime: Any,
) -> Dict[str, Any]:
    """Auto-GLM planning-tap-locator (models/auto-glm/locate.ts)."""
    locator = create_auto_glm_planning_tap_locator(
        model_runtime.adapter.family == "auto-glm-multilingual"
    )
    return await run_planning_action_locate(
        locator, target_element_description, locate_image, model_runtime
    )


__all__ = ["auto_glm_locate", "create_auto_glm_planning_tap_locator"]
