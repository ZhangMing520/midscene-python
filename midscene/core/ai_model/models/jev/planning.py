"""Jev planning workflow (upstream models/jev/planning.ts)."""

import json
from typing import Any

from midscene.core.ai_model.models.jev.planning_action import (
    build_jev_action,
)
from midscene.core.ai_model.models.jev.planning_context import (
    prepare_jev_planning_context,
)
from midscene.core.ai_model.models.jev.planning_decision import (
    decide_jev_action,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.system_one import SystemOneError
from midscene.core.ai_model.shared.multimodal_prompt import get_shot_size


async def jev_plan(
    instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: list[Any],
    conversation_history: Any,
    include_locate_in_planning: bool = False,
    action_context: str | None = None,
    reference_images: list[str] | None = None,
) -> dict[str, Any]:
    """Jev planning via System One choice questions."""
    if len(action_space) + 2 > 255:
        raise SystemOneError(
            "Jev planning supports at most 253 actions (255 choices including "
            "completion and delegation)."
        )
    jev_context = await prepare_jev_planning_context(
        instruction,
        context,
        model_runtime,
        action_space,
        conversation_history,
        action_context,
        reference_images,
    )
    decision = await decide_jev_action(
        jev_context, model_runtime, action_space, include_locate_in_planning
    )
    selected = decision["selected"]
    choice = decision["choice"]
    response = decision["response"]

    def yaml_flow_of(actions: list[dict[str, Any]]) -> str:
        import yaml

        flow = [
            {"type": action["type"], **(action.get("param") or {})}
            for action in actions
        ]
        return yaml.dump(flow, allow_unicode=True, sort_keys=False, width=10**6).strip()

    if choice["kind"] == "delegate":
        return {
            "actions": [],
            "log": f"Jev selected {selected}",
            "raw_response": response["content"],
            "usage": response["usage"],
            "should_continue_planning": True,
            "delegation": {
                "reason": (
                    f"The previous planner suggested {choice['action'].name}; "
                    "delegating planning with this action as an advisory suggestion"
                    if choice.get("action")
                    else "The previous planner delegated planning of the next step"
                ),
                "suggestedAction": choice["action"].name
                if choice.get("action")
                else None,
            },
        }

    actions = build_jev_action(
        decision,
        jev_context,
        instruction,
        action_space,
        include_locate_in_planning,
        get_shot_size(context),
        reference_images,
    )
    log = f"Jev selected {selected}"
    feedback = conversation_history.pending_feedback_message
    conversation_history.reset_pending_feedback_message_if_exists()
    conversation_history.append_message(
        {
            "role": "user",
            "content": f"Goal: {instruction}\nExecution feedback: {feedback}",
        }
    )
    conversation_history.append_message(
        {
            "role": "assistant",
            "content": json.dumps({"actions": actions, "log": log}),
        }
    )
    conversation_history.append_historical_log(
        f"{log}: {json.dumps([{'type': a['type'], 'direction': (a.get('param') or {}).get('direction')} for a in actions])}"
    )
    conversation_history.compress_history(50, 20)
    return {
        "actions": actions,
        "log": log,
        "raw_response": response["content"],
        "usage": response["usage"],
        "should_continue_planning": choice["kind"] != "complete",
        **({"finalize_success": True} if choice["kind"] == "complete" else {}),
        "yaml_flow": yaml_flow_of(actions),
    }
