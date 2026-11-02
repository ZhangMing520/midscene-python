"""Jev model family workflows (System One protocol).

Synced from upstream packages/core/src/ai-model/models/jev/*
(image.ts, locate.ts, boolean.ts, planning.ts, planning-context.ts,
planning-decision.ts, planning-action.ts).
"""

import base64
import io
import json
from typing import Any, Dict, List, Optional


from ..adapters import ModelRuntime
from ..system_one import SystemOneError, call_system_one, validate_system_one_response
from .context_utils import get_screenshot_base64, get_shot_size
from ..locate_result import create_locate_result_codec

# Jev boxes are normalized 0-1 with edges semantics.
_jev_box_codec = create_locate_result_codec(
    {
        "coordinates": {
            "shape": "bbox",
            "normalizedBy": 1,
            "rounding": "none",
            "boundsType": "edges",
        }
    }
)


def prepare_jev_image(image_url: str) -> str:
    """Normalize an image to a JPEG/PNG data URL under 16 MiB."""
    raw = image_url
    if raw.startswith("data:"):
        header, body = raw.split(",", 1)
        if len(body.encode()) > 16 * 1024 * 1024 // 4 * 3:
            raise SystemOneError("Jev image exceeds 16 MiB")
        if header.startswith("data:image/png") or header.startswith("data:image/jpeg"):
            return raw
        # convert to jpeg
        from PIL import Image

        image = Image.open(io.BytesIO(base64.b64decode(body))).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    # raw base64 -> jpeg data url
    if len(raw.encode()) > 16 * 1024 * 1024 // 4 * 3:
        raise SystemOneError("Jev image exceeds 16 MiB")
    return "data:image/jpeg;base64," + raw


def map_jev_box(
    box: Dict[str, float], target_size: Dict[str, Any]
) -> Dict[str, Any]:
    """Map a normalized 0-1 Jev box to pixel {center, rect}."""
    return _jev_box_codec.to_pixel_result(
        [box["left"], box["top"], box["right"], box["bottom"]],
        {"preparedSize": target_size},
    )


def _parse_answers(content: str) -> Dict[str, Any]:
    return validate_system_one_response(json.loads(content))["answers"]


# ---------------------------------------------------------------------------
# Locate (jev/locate.ts)
# ---------------------------------------------------------------------------

async def jev_locate(
    target_element_description: Any,
    locate_image: Dict[str, Any],
    model_runtime: ModelRuntime,
) -> Dict[str, Any]:
    """Jev locate: returns {locatedPixelResult?} | {errors?}, plus raw/usage."""
    image = prepare_jev_image(locate_image["imageBase64"])
    target = (
        target_element_description
        if isinstance(target_element_description, str)
        else str(target_element_description.get("prompt", ""))
    )
    response = await call_system_one(
        model_runtime,
        {
            "state": {"target": target},
            "images": {"screenshot": image},
            "questions": {
                "present": {
                    "type": "noul",
                    "instructions": (
                        "Is the target described in `target` present in "
                        "`screenshot`? Reference images, if any, describe the "
                        "target; they are not the screenshot."
                    ),
                },
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
    if answers["present"]["type"] != "noul" or answers["target"]["type"] != "box":
        raise SystemOneError("Invalid Jev locate answers")

    result: Dict[str, Any] = {
        "raw_response": response["content"],
        "usage": response["usage"],
    }
    if answers["present"]["noul"] >= 0.5:
        result["locatedPixelResult"] = map_jev_box(
            answers["target"]["box"],
            {"width": locate_image["width"], "height": locate_image["height"]},
        )
    else:
        result["errors"] = ["The target is not present in the screenshot"]
    return result


# ---------------------------------------------------------------------------
# Boolean (jev/boolean.ts)
# ---------------------------------------------------------------------------

async def jev_boolean(
    statement: str,
    context: Any,
    model_runtime: ModelRuntime,
    page_description: str = "",
    context_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Jev boolean: returns {value, raw_response, usage}."""
    screenshot = prepare_jev_image(get_screenshot_base64(context))
    result = await call_system_one(
        model_runtime,
        {
            "state": {
                "statement": statement,
                "context": context_text,
                "pageDescription": page_description,
                "frames": ["`frame_0`"],
            },
            "images": {"frame_0": screenshot},
            "questions": {
                "result": {
                    "type": "noul",
                    "instructions": (
                        "Is `statement` true? Screenshots in `frames` are ordered "
                        "earliest to latest. For current state use the latest "
                        "frame; for events use the relevant frames. Reference "
                        "images are supporting context, not screenshots, unless "
                        "the statement requests comparison. Use the provided "
                        "context and page description when present."
                    ),
                }
            },
        },
    )
    answers = result["answers"]
    if answers["result"]["type"] != "noul":
        raise SystemOneError("Invalid Jev boolean answer")
    return {
        "value": answers["result"]["noul"] >= 0.5,
        "raw_response": result["content"],
        "usage": result["usage"],
    }


# ---------------------------------------------------------------------------
# Planning (jev/planning.ts + planning-context.ts + planning-decision.ts +
# planning-action.ts)
# ---------------------------------------------------------------------------

async def prepare_jev_planning_context(
    instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: Any,
    action_context: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
) -> Dict[str, Any]:
    screenshot = prepare_jev_image(get_screenshot_base64(context))
    state = {
        "goal": instruction,
        "context": action_context,
        "history": conversation_history.historical_logs_to_text(),
        "memory": conversation_history.memories_to_text(),
        "feedback": conversation_history.pending_feedback_message,
        "availableActions": [
            {"name": action.name, "description": action.description}
            for action in action_space
        ],
    }
    images = {"screenshot": screenshot}
    reference_keys = []
    for _index, _url in enumerate(reference_images or []):
        _key = f"reference_{_index}"
        images[_key] = _url
        reference_keys.append(_key)
    if reference_keys:
        state["referenceImages"] = reference_keys
    return {"state": state, "images": images}


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


def build_jev_action(
    decision: Dict[str, Any],
    jev_context: Dict[str, Any],
    instruction: str,
    action_space: List[Any],
    include_locate_in_planning: bool,
    shot_size: Dict[str, Any],
) -> List[Dict[str, Any]]:
    choice = decision["choice"]
    if choice["kind"] == "complete":
        return []
    if choice["kind"] != "action":
        raise SystemOneError("Delegated actions must use the default planner")
    action = choice["action"]
    fields = list(action.locate_fields)
    located_pixel_result = None
    if include_locate_in_planning and len(fields) == 1:
        if not decision.get("target") or decision["target"].get("type") != "box":
            raise SystemOneError("Missing Jev planning target box")
        located_pixel_result = map_jev_box(decision["target"]["box"], shot_size)

    param = {
        field: {
            "prompt": (
                f"Locate the target for parameter {json.dumps(field)} of action "
                f"{json.dumps(action.name)} ({action.description or action.name}) "
                "for the NEXT step toward this goal. Use the current screenshot "
                "as authoritative and consider execution feedback. Task context: "
                f"{json.dumps(jev_context['state'])}"
            ),
            **({"locatedPixelResult": located_pixel_result} if located_pixel_result else {}),
        }
        for field in fields
    }
    return [{"type": action.name, "param": param}]


async def jev_plan(
    instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: Any,
    include_locate_in_planning: bool = False,
    action_context: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
) -> Dict[str, Any]:
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

    def yaml_flow_of(actions: List[Dict[str, Any]]) -> str:
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
                "suggestedAction": choice["action"].name if choice.get("action") else None,
            },
        }

    actions = build_jev_action(
        decision,
        jev_context,
        instruction,
        action_space,
        include_locate_in_planning,
        get_shot_size(context),
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
        f"{log}: {json.dumps([{ 'type': a['type'], 'direction': (a.get('param') or {}).get('direction')} for a in actions])}"
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
