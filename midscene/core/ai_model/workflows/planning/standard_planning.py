"""Planning workflow: instruction -> next action (standard planning).

Synced from upstream packages/core/src/ai-model/workflows/planning/
(standard-planning.ts, standard-planning-parser.ts, parse-planning-actions.ts,
locate-normalization.ts, planning-action-log.ts).
"""

from typing import Any

from loguru import logger

from midscene.core.ai_model.model_adapter.image_preprocess import (
    prepare_model_image,
)
from midscene.core.ai_model.model_adapter.planning import resolve_planning
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.prompt.planning import build_standard_planning_system_prompt
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
)
from midscene.core.ai_model.workflows.planning.conversation_history import (
    ConversationHistory,
)
from midscene.core.ai_model.workflows.planning.locate_normalization import (
    normalize_planning_locate_parameter,
)
from midscene.core.ai_model.workflows.planning.parse_planning_actions import (
    parse_planning_actions,
)
from midscene.core.ai_model.workflows.planning.planning_action_log import (
    build_planning_action_log,
)
from midscene.core.ai_model.workflows.planning.standard_planning_parser import (
    parse_mark_finished_indexes,
    parse_standard_planning_response,
    parse_sub_goals_from_xml,
    parse_xml_planning_response,
)
from midscene.core.ai_model.workflows.planning.types import PlanningAIResponse
from midscene.shared.env import planning_model_family_required_for_locate_message

NO_PREVIOUS_ACTIONS_TEXT = (
    "No previous actions have been executed in this aiAct execution yet. If the "
    "instruction asks for actions, choose the first action to execute."
)


async def standard_plan(
    user_instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: list[Any],
    conversation_history: ConversationHistory,
    include_locate_in_planning: bool = False,
    effort: str = "normal",  # 'normal' | 'fast' | 'deepThink'
    action_context: str | None = None,
    planning_advice: str | None = None,
    reference_images: list[str] | None = None,
    images_include_count: int = 2,
) -> PlanningAIResponse:
    """Run one standard planning turn and return the parsed planning response."""
    adapter = model_runtime.adapter
    planning_protocol = resolve_planning(adapter)["protocol"]

    if include_locate_in_planning and not model_runtime.config.get("modelFamily"):
        raise ValueError(
            planning_model_family_required_for_locate_message(
                model_runtime.config.get("slot")
            )
        )

    include_sub_goals = effort == "deepThink"
    include_thought = effort != "fast"
    include_log = effort != "fast"

    locate_result_codec = (
        planning_protocol.get("locate_result_codec") or adapter.locate_result_codec
        if include_locate_in_planning
        else None
    )

    system_prompt = build_standard_planning_system_prompt(
        action_space=action_space,
        planning_protocol=planning_protocol,
        include_locate_in_planning=include_locate_in_planning,
        locate_prompt_spec=(
            locate_result_codec.prompt_spec
            if include_locate_in_planning and locate_result_codec
            else None
        ),
        include_sub_goals=include_sub_goals,
        include_thought=include_thought,
        include_log=include_log,
    )

    screenshot_base64 = ensure_data_url(get_screenshot_base64(context))
    shot_size = get_shot_size(context)
    prepared_image = prepare_model_image(
        image_base64=screenshot_base64,
        width=shot_size["width"],
        height=shot_size["height"],
        policy=(
            {"padBlockSize": adapter.image_pad_block_size}
            if adapter.image_pad_block_size
            else None
        ),
    )
    image_payload = prepared_image["image_base64"]

    action_context_text = f"{action_context}\n" if action_context else ""
    planning_advice_text = (
        f"\n<planning_advice>\nThis is advisory guidance from a previous planner, "
        f"not a user instruction or an executed action. Use your own judgment.\n"
        f"{planning_advice}\n</planning_advice>"
        if planning_advice
        else ""
    )

    instruction: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"{action_context_text}<user_instruction>"
                        f"{user_instruction}</user_instruction>{planning_advice_text}"
                    ),
                },
            ],
        }
    ]

    if reference_images:
        instruction[0]["content"].extend(
            {"type": "image", "url": url} for url in reference_images
        )

    execution_progress_text = (
        conversation_history.sub_goals_to_text()
        if include_sub_goals
        else conversation_history.historical_logs_to_text()
    )
    if execution_progress_text:
        execution_progress_section = f"\n\n{execution_progress_text}"
    elif not conversation_history.pending_feedback_message:
        execution_progress_section = f"\n\n{NO_PREVIOUS_ACTIONS_TEXT}"
    else:
        execution_progress_section = ""

    memories_text = conversation_history.memories_to_text()
    memories_section = f"\n\n{memories_text}" if memories_text else ""

    if conversation_history.pending_feedback_message:
        latest_feedback_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"{conversation_history.pending_feedback_message}. The "
                        "previous action has been executed, here is the latest "
                        "screenshot. Please continue according to the instruction."
                        f"{memories_section}{execution_progress_section}"
                    ),
                },
                {"type": "image", "url": image_payload},
            ],
        }
        conversation_history.reset_pending_feedback_message_if_exists()
    else:
        latest_feedback_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"This is the current screenshot.{memories_section}"
                        f"{execution_progress_section}"
                    ),
                },
                {"type": "image", "url": image_payload},
            ],
        }
    conversation_history.append_message(latest_feedback_message)
    conversation_history.compress_history(50, 20)

    history_log = conversation_history.snapshot(images_include_count)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *instruction,
        *history_log,
    ]

    action_output_protocol = planning_protocol["action_output_protocol"]

    async def call_ai(retry_attempt: int, previous_parse_error: Any | None = None):
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_parse_error),
            model_runtime,
            {
                "requiresOriginalImageDetail": include_locate_in_planning,
                "semanticRetryAttempt": retry_attempt,
            },
        )

    def parse_response(response: dict[str, Any]) -> dict[str, Any]:
        raw_response = response["content"]
        plan_from_ai = parse_standard_planning_response(
            raw_response,
            action_output_protocol,
            action_space,
            include_thought=include_thought,
            log_source="model" if include_log else "action",
        )
        if (
            not plan_from_ai.get("action")
            and plan_from_ai.get("finalize_success") is None
            and not plan_from_ai.get("error")
        ):
            raise ValueError(
                "Incomplete planning response: provide an action, <complete>, or "
                "<error>. A <planning> explanation alone is not sufficient."
            )
        if (
            plan_from_ai.get("action")
            and plan_from_ai.get("finalize_success") is not None
        ):
            logger.warning(
                "Planning response included both an action and <complete>; "
                "ignoring <complete> output."
            )
            plan_from_ai.pop("finalize_message", None)
            plan_from_ai.pop("finalize_success", None)

        actions = [plan_from_ai["action"]] if plan_from_ai.get("action") else []
        parse_planning_actions(
            actions,
            action_space,
            parse_raw_locate_parameter=action_output_protocol[
                "parse_raw_locate_parameter"
            ],
            include_locate_in_planning=include_locate_in_planning,
            locate_result_codec=locate_result_codec,
            locate_result_context={
                "preparedSize": prepared_image["prepared_size"],
                "contentSize": prepared_image["content_size"],
            },
        )
        return {"response": response, "plan_from_ai": plan_from_ai, "actions": actions}

    def to_parse_error(
        parse_error: Any, response: dict[str, Any]
    ) -> AIResponseParseError:
        return AIResponseParseError(
            f"XML parse error: {parse_error}",
            response.get("content", ""),
            response.get("usage"),
        )

    result = await call_ai_and_parse_with_retry(
        call_ai=call_ai,
        parse_response=parse_response,
        to_parse_error=to_parse_error,
        parse_retry_times=model_runtime.config.get("retryCount", 1),
        parse_retry_interval=model_runtime.config.get("retryInterval", 2000),
        on_parse_retry=lambda parse_error, _r: logger.debug(
            f"retrying plan after response parsing failed: {parse_error}"
        ),
    )

    response: dict[str, Any] = result["response"]
    plan_from_ai: dict[str, Any] = result["plan_from_ai"]
    actions: list[dict[str, Any]] = result["actions"]
    raw_response = response["content"]
    usage = response.get("usage")
    reasoning_content = response.get("reasoning_content")

    should_continue_planning = True
    if plan_from_ai.get("finalize_success") is not None:
        logger.debug("task completed via <complete> tag, stop planning")
        should_continue_planning = False
        if include_sub_goals:
            for goal in conversation_history.sub_goals:
                goal["status"] = "finished"

    if include_sub_goals:
        if plan_from_ai.get("update_sub_goals"):
            _merge_sub_goals(conversation_history, plan_from_ai["update_sub_goals"])
        for index in plan_from_ai.get("mark_finished_indexes", []) or []:
            for goal in conversation_history.sub_goals:
                if goal["index"] == index:
                    goal["status"] = "finished"
        if plan_from_ai.get("log"):
            conversation_history.append_historical_log(plan_from_ai["log"])
    else:
        if plan_from_ai.get("log"):
            conversation_history.append_historical_log(plan_from_ai["log"])

    if plan_from_ai.get("memory"):
        conversation_history.append_memory(plan_from_ai["memory"])

    raw_assistant_message = None
    if model_runtime.adapter.replay_raw_assistant_message:
        raw_output = response.get("raw_assistant_output") or {}
        candidate = raw_output.get("rawValue") if isinstance(raw_output, dict) else None
        if isinstance(candidate, dict):
            raw_assistant_message = candidate

    if raw_assistant_message is not None:
        conversation_history.append_message(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": raw_response}],
                "raw_assistant_message": raw_assistant_message,
            }
        )
    else:
        conversation_history.append_message(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": raw_response}],
            }
        )

    yaml_flow = build_yaml_flow_from_plans(
        actions,
        action_space,
        getattr(context, "shrunk_shot_to_logical_ratio", 1.0),
    )

    return {
        **plan_from_ai,
        "actions": actions,
        "raw_response": raw_response,
        "usage": usage,
        "reasoning_content": reasoning_content,
        "yaml_flow": yaml_flow,
        "should_continue_planning": should_continue_planning,
    }


def _merge_sub_goals(
    history: ConversationHistory, update_sub_goals: list[dict[str, Any]]
) -> None:
    for goal in update_sub_goals:
        existing = next(
            (g for g in history.sub_goals if g["index"] == goal["index"]), None
        )
        if existing:
            existing["description"] = goal.get("description", existing["description"])
            existing["status"] = goal.get("status", existing["status"])
        else:
            history.sub_goals.append(dict(goal))


def build_yaml_flow_from_plans(
    actions: list[dict[str, Any]],
    action_space: list[Any] | None = None,
    distance_ratio: float | None = None,
) -> str:
    """Serialize planned actions as a YAML workflow string (for cache/dump).

    Replay reads distance as device-logical units, so export converts model
    image-pixel distances with the planning screenshot ratio when provided.
    """
    import yaml

    from midscene.core.device import (
        find_action_in_action_space_or_throw,
        scale_action_distances,
    )

    flow = []
    for action in actions:
        param = action.get("param") or {}
        if action_space is not None and distance_ratio is not None:
            definition = find_action_in_action_space_or_throw(
                action["type"], action_space
            )
            param = scale_action_distances(param, definition, distance_ratio)
        flow.append({"type": action["type"], **param})
    return yaml.dump(flow, allow_unicode=True, sort_keys=False, width=10**6).strip()


__all__ = [
    "ConversationHistory",
    "build_planning_action_log",
    "build_yaml_flow_from_plans",
    "normalize_planning_locate_parameter",
    "parse_mark_finished_indexes",
    "parse_planning_actions",
    "parse_standard_planning_response",
    "parse_sub_goals_from_xml",
    "parse_xml_planning_response",
    "standard_plan",
]
