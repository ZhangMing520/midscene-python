"""Jev planning decision (upstream models/jev/planning-decision.ts)."""

from typing import Any, Dict, List
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.system_one import SystemOneError, call_system_one

async def decide_jev_action(
    jev_context: Dict[str, Any],
    model_runtime: ModelRuntime,
    action_space: List[Any],
    include_locate_in_planning: bool,
) -> Dict[str, Any]:
    criteria: Dict[str, str] = {
        "control:complete": (
            "The entire user goal is already satisfied, confirmed by the current "
            "screenshot and execution feedback. No text answer is requested."
        ),
        "control:delegate": (
            "The next step needs generated output, an explanation of why the task "
            "cannot be completed, or something not covered by the action choices. "
            "Delegate to the default model."
        ),
    }
    choices: Dict[str, Dict[str, Any]] = {
        "control:complete": {"kind": "complete"},
        "control:delegate": {"kind": "delegate"},
    }
    for action in action_space:
        kind = "action" if action.supported_by_system_one else "delegate"
        key = f"{kind}:{action.name}"
        if key in choices:
            raise SystemOneError(f"Duplicate Jev planning choice: {key}")
        choices[key] = {"kind": kind, "action": action}
        criteria[key] = (
            f"{action.name}: {action.description or action.name}. "
            + (
                "Perform this action."
                if kind == "action"
                else "Suggest this action and delegate the next planning step, "
                "including its parameters, to the default model."
            )
        )
    if len(choices) > 255:
        raise SystemOneError("Jev Choice supports at most 255 options")

    locate_in_planning = (
        include_locate_in_planning
        and any(
            action.supported_by_system_one and len(action.locate_fields) == 1
            for action in action_space
        )
    )

    questions: Dict[str, Any] = {
        "action": {
            "type": "choice",
            "instructions": (
                "Choose exactly the next step toward `goal` using the current "
                "`screenshot`, context, history and feedback. History records "
                "proposed actions; feedback and current screenshot establish what "
                "actually happened. Do not repeat completed steps. Reference "
                "images describe targets, not the current page. A delegate choice "
                "means the named action is likely needed; it has not been "
                "executed. Choose control:complete only when no requested work or "
                "text answer remains."
            ),
            "criteria": criteria,
        }
    }
    if locate_in_planning:
        questions["target"] = {
            "type": "box",
            "instructions": (
                "Identify the single UI element to interact with in the NEXT step "
                "toward `goal`, using the current `screenshot`, context, history "
                "and feedback. Return its bounding box in `screenshot`. This is "
                "the target of the next direct action (such as Tap, DoubleClick, "
                "Hover or ClearInput), not the final goal of the entire task. "
                "Reference images describe targets, not the current page. If the "
                "next step needs no target or must be delegated, this box is "
                "unused."
            ),
        }

    response = await call_system_one(model_runtime, {**jev_context, "questions": questions})
    answers = response["answers"]
    if answers["action"]["type"] != "choice":
        raise SystemOneError("Invalid Jev planning action")
    selected = answers["action"]["choice"]
    choice = choices.get(selected)
    if choice is None:
        raise SystemOneError(f"Unknown Jev planning choice: {selected}")
    return {
        "selected": selected,
        "choice": choice,
        "response": response,
        "target": answers.get("target") if locate_in_planning else None,
    }
