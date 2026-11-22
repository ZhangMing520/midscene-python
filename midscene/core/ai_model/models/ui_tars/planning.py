"""UI-TARS custom planner (upstream ai-model/models/ui-tars/planning.ts)."""

from typing import Any, Dict, List, Optional

from midscene.core.ai_model.models.ui_tars.actions import transform_ui_tars_actions
from midscene.core.ai_model.models.ui_tars.parser import (
    parse_ui_tars_planning_response,
)
from midscene.core.ai_model.models.ui_tars.prompt import (
    _ui_tars_summary,
    get_ui_tars_planning_prompt,
)
from midscene.core.ai_model.model_adapter.custom_planning_types import (
    CustomPlanningDefinition,
)
from midscene.core.ai_model.shared.multimodal_prompt import get_shot_size

UI_TARS_COORDINATES = {"shape": "point", "order": "xy", "normalizedBy": 1}


def _build_no_ui_tars_actions_error(
    raw_response: str,
    actions: List[Dict[str, Any]],
    unhandled_actions: List[Dict[str, Any]],
) -> str:
    message = "No actions found in UI-TARS response."
    if len(actions) == 0:
        message += "Action parser returned no actions"
        if "Thought:" in raw_response and "Action:" not in raw_response:
            message += 'Response contains "Thought:" but missing "Action:" line'
        else:
            message += "Response may be malformed or empty"
    if unhandled_actions:
        types = ", ".join(a["type"] for a in unhandled_actions)
        message += f"Unhandled action types: {types}"
    return message


def _transform_ui_tars_with_error(
    parsed_response: Dict[str, Any],
) -> List[Dict[str, Any]]:
    transformed, unhandled = transform_ui_tars_actions(parsed_response)
    if len(transformed) == 0:
        raise ValueError(
            _build_no_ui_tars_actions_error(
                parsed_response.get("rawResponse", ""),
                parsed_response.get("actions", []),
                unhandled,
            )
        )
    return transformed


def create_ui_tars_planner(
    ui_tars_model_version: Optional[str] = None,
) -> CustomPlanningDefinition:
    return {
        "messages": {
            "system_prompt_placement": "user-message",
            "build_system_prompt": get_ui_tars_planning_prompt,
            "build_user_instruction": (
                lambda instruction: f"<user_instruction>{instruction}</user_instruction>"
            ),
            "build_assistant_content": lambda parsed, raw: _ui_tars_summary(raw),
        },
        "coordinates": UI_TARS_COORDINATES,
        "parse_response": lambda raw, context, runtime: parse_ui_tars_planning_response(
            raw, get_shot_size(context), ui_tars_model_version
        ),
        "transform_actions": lambda parsed, context, action_space, runtime: (
            _transform_ui_tars_with_error(parsed)
        ),
        "should_continue_planning": lambda parsed, actions: all(
            action["type"] != "Finished" for action in actions
        ),
        "build_response_log": lambda parsed, raw: _ui_tars_summary(raw),
    }


__all__ = ["UI_TARS_COORDINATES", "create_ui_tars_planner"]
