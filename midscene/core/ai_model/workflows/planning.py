"""Planning workflow: instruction -> next action (standard planning).

Synced from upstream packages/core/src/ai-model/workflows/planning/
(standard-planning.ts, standard-planning-parser.ts, parse-planning-actions.ts,
locate-normalization.ts, planning-action-log.ts).
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..caller import AIResponseParseError, call_generative_ai
from ..prompts.planning import build_standard_planning_system_prompt
from ..semantic_retry import call_ai_and_parse_with_retry, with_semantic_retry_feedback
from ..adapters import ModelRuntime
from ..env_config import planning_model_family_required_for_locate_message
from ..xml_utils import extract_raw_xml_fragment, extract_xml_tag
from .context_utils import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
    prepare_model_image,
)

NO_PREVIOUS_ACTIONS_TEXT = (
    "No previous actions have been executed in this aiAct execution yet. If the "
    "instruction asks for actions, choose the first action to execute."
)


# ---------------------------------------------------------------------------
# Response parsing (standard-planning-parser.ts)
# ---------------------------------------------------------------------------

_SUB_GOAL_RE = re.compile(
    r'<sub-goal\s+index="(\d+)"\s+status="(pending|finished)"(?:\s*/>|>([\s\S]*?)</sub-goal>)',
    re.IGNORECASE,
)
_MARK_SUB_GOAL_DONE_RE = re.compile(
    r'<sub-goal\s+index="(\d+)"\s+status="finished"\s*/>', re.IGNORECASE
)
_COMPLETE_RE = re.compile(r'<complete\s+success="(true|false)">([\s\S]*?)</complete>', re.IGNORECASE)


def parse_sub_goals_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    sub_goals: List[Dict[str, Any]] = []
    for match in _SUB_GOAL_RE.finditer(xml_content):
        sub_goals.append(
            {
                "index": int(match.group(1)),
                "status": match.group(2),
                "description": (match.group(3) or "").strip(),
            }
        )
    return sub_goals


def parse_mark_finished_indexes(xml_content: str) -> List[int]:
    return [int(match.group(1)) for match in _MARK_SUB_GOAL_DONE_RE.finditer(xml_content)]


def parse_xml_planning_response(
    xml_string: str,
    action_output_tag_names: Tuple[str, ...],
    include_thought: bool,
) -> Tuple[Dict[str, Any], str]:
    """Parse common XML fields and retain the raw action-protocol XML."""
    thought = extract_xml_tag(xml_string, "planning") if include_thought else None
    memory = extract_xml_tag(xml_string, "memory")
    log = extract_xml_tag(xml_string, "log") or ""
    error = extract_xml_tag(xml_string, "error")

    complete_match = _COMPLETE_RE.search(xml_string)
    finalize_message: Optional[str] = None
    finalize_success: Optional[bool] = None
    if complete_match:
        finalize_success = complete_match.group(1) == "true"
        finalize_message = complete_match.group(2).strip() or None

    update_plan_content = extract_xml_tag(xml_string, "update-plan-content")
    mark_sub_goal_done = extract_xml_tag(xml_string, "mark-sub-goal-done")
    update_sub_goals = (
        parse_sub_goals_from_xml(update_plan_content) if update_plan_content else None
    )
    mark_finished_indexes = (
        parse_mark_finished_indexes(mark_sub_goal_done) if mark_sub_goal_done else None
    )

    parsed: Dict[str, Any] = {"log": log}
    if thought:
        parsed["thought"] = thought
    if memory:
        parsed["memory"] = memory
    if error:
        parsed["error"] = error
    if finalize_message is not None:
        parsed["finalize_message"] = finalize_message
    if finalize_success is not None:
        parsed["finalize_success"] = finalize_success
    if update_sub_goals:
        parsed["update_sub_goals"] = update_sub_goals
    if mark_finished_indexes:
        parsed["mark_finished_indexes"] = mark_finished_indexes

    raw_action_output = extract_raw_xml_fragment(xml_string, action_output_tag_names)
    return parsed, raw_action_output


def _build_non_action_planning_log(response: Dict[str, Any]) -> str:
    if response.get("error"):
        return f"Error - {response['error']}"
    if response.get("finalize_success") is not None:
        parts = [f"Complete - success: {str(response['finalize_success']).lower()}"]
        if response.get("finalize_message"):
            parts.append(f"message: {response['finalize_message']}")
        return ", ".join(parts)
    return "No action"


def build_planning_action_log(action: Dict[str, Any], action_space: List[Any]) -> str:
    """Build a human-readable log line for an executed planning action."""
    action_dict = next(
        (
            (a if isinstance(a, dict) else a.to_prompt_dict())
            for a in action_space
            if (a if isinstance(a, dict) else a.to_prompt_dict())["name"]
            == action["type"]
        ),
        None,
    )
    param = action.get("param") or {}
    locate = param.get("locate") or {}
    target = (
        locate.get("prompt") if isinstance(locate, dict) else None
    ) or param.get("value") or param.get("keyName") or ""
    interface_alias = (action_dict or {}).get("interface_alias")
    return f"{interface_alias or action['type']}({target})"


def parse_standard_planning_response(
    xml_string: str,
    action_output_protocol: Dict[str, Any],
    action_space: List[Any],
    include_thought: bool,
    log_source: str = "model",
) -> Dict[str, Any]:
    parsed, raw_action_output = parse_xml_planning_response(
        xml_string, action_output_protocol["action_output_tag_names"], include_thought
    )
    response = dict(parsed)
    response["action"] = action_output_protocol["parse_action_output"](
        raw_action_output, action_space
    )

    if log_source == "model":
        return response

    if response.get("action"):
        response["log"] = build_planning_action_log(response["action"], action_space)
    else:
        response["log"] = _build_non_action_planning_log(response)
    return response


# ---------------------------------------------------------------------------
# Planning action parameter normalization (parse-planning-actions.ts +
# locate-normalization.ts)
# ---------------------------------------------------------------------------

def normalize_planning_locate_parameter(
    locate: Dict[str, Any],
    locate_result_codec: Optional[Any],
    locate_result_context: Optional[Dict[str, Any]],
    include_locate_in_planning: bool,
) -> Dict[str, Any]:
    """Normalize a planning locate parameter into {prompt, ...}.

    When the planning model returned coordinates (includeLocateInPlanning) they
    are mapped to pixels and attached as `locatedPixelResult`; otherwise the
    parameter keeps only the prompt and locate runs at execution time.
    """
    prompt = locate.get("prompt")
    if not include_locate_in_planning:
        return {"prompt": prompt}

    if locate_result_codec is None:
        raise ValueError(
            "planning locate normalization requires a locate result codec"
        )

    spec = locate_result_codec.prompt_spec
    raw_keys = [spec["resultKey"], *(spec.get("resultKeyAliases") or [])]
    raw_value = next(
        (locate[key] for key in raw_keys if key in locate), None
    )
    # Drop raw coordinate fields after converting them.
    normalized = {key: value for key, value in locate.items() if key not in raw_keys}
    normalized["locatedPixelResult"] = locate_result_codec.to_pixel_result(
        raw_value, locate_result_context or {}
    )
    return normalized


def parse_planning_actions(
    actions: List[Dict[str, Any]],
    action_space: List[Any],
    parse_raw_locate_parameter,
    include_locate_in_planning: bool,
    locate_result_codec: Optional[Any] = None,
    locate_result_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Validate and normalize planning actions in place."""
    from ...actions import find_action_in_action_space_or_throw

    for action in actions:
        definition = find_action_in_action_space_or_throw(action["type"], action_space)
        locate_fields = list(definition.locate_fields) if not isinstance(definition, dict) else list(
            definition.get("locate_fields", [])
        )
        try:
            param = action.get("param")
            if param is None:
                param = {}
                action["param"] = param

            for field in locate_fields:
                raw_locate = param.get(field)
                if raw_locate is not None:
                    param[field] = parse_raw_locate_parameter(raw_locate)

            for field in locate_fields:
                locate = param.get(field)
                if locate is None:
                    continue
                if not isinstance(locate, dict):
                    raise ValueError(f"{field}: Expected an object with a prompt field")
                if locate.get("prompt") is None:
                    raise ValueError(f"{field}.prompt: Required")
                if not isinstance(locate["prompt"], str) and not isinstance(
                    locate["prompt"], dict
                ):
                    raise ValueError(
                        f"{field}.prompt: Expected a string or an object with a prompt field"
                    )
                param[field] = normalize_planning_locate_parameter(
                    locate,
                    locate_result_codec,
                    locate_result_context,
                    include_locate_in_planning,
                )
        except Exception as error:
            raise ValueError(
                f"Invalid parameters for action {action['type']}: {error}"
            ) from error


# ---------------------------------------------------------------------------
# Conversation history (conversation-history.ts, simplified subset)
# ---------------------------------------------------------------------------

class ConversationHistory:
    """Track messages, historical logs and memories across planning turns."""

    def __init__(self, images_include_count: int = 2):
        self.messages: List[Dict[str, Any]] = []
        self.historical_logs: List[str] = []
        self.memories: List[str] = []
        self.sub_goals: List[Dict[str, Any]] = []
        self.pending_feedback_message: Optional[str] = None
        self.images_include_count = images_include_count

    def append_message(self, message: Dict[str, Any]) -> None:
        self.messages.append(message)

    def append_historical_log(self, log: str) -> None:
        if log:
            self.historical_logs.append(log)

    def append_memory(self, memory: str) -> None:
        if memory:
            self.memories.append(memory)

    def reset_pending_feedback_message_if_exists(self) -> None:
        self.pending_feedback_message = None

    def historical_logs_to_text(self) -> str:
        if not self.historical_logs:
            return ""
        lines = "\n".join(f"- {log}" for log in self.historical_logs)
        return f"### Historical execution logs\n{lines}"

    def memories_to_text(self) -> str:
        if not self.memories:
            return ""
        lines = "\n".join(f"- {memory}" for memory in self.memories)
        return f"### Memories\n{lines}"

    def sub_goals_to_text(self) -> str:
        from ..prompts.planning import build_sub_goals_text

        return build_sub_goals_text(self.sub_goals)

    def snapshot(self, images_include_count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return recent history, keeping at most N images."""
        limit = (
            images_include_count
            if images_include_count is not None
            else self.images_include_count
        )
        result: List[Dict[str, Any]] = []
        image_count = 0
        for message in reversed(self.messages):
            content = message.get("content")
            has_image = isinstance(content, list) and any(
                part.get("type") == "image" for part in content
            )
            if has_image:
                if image_count >= limit:
                    continue
                image_count += 1
            result.append(message)
        result.reverse()
        return result

    def compress_history(self, threshold: int = 50, keep: int = 20) -> None:
        if len(self.messages) <= threshold:
            return
        self.messages = self.messages[-keep:]


# ---------------------------------------------------------------------------
# standardPlan (standard-planning.ts)
# ---------------------------------------------------------------------------

async def standard_plan(
    user_instruction: str,
    context: Any,
    model_runtime: ModelRuntime,
    action_space: List[Any],
    conversation_history: ConversationHistory,
    include_locate_in_planning: bool = False,
    effort: str = "normal",  # 'normal' | 'fast' | 'deepThink'
    action_context: Optional[str] = None,
    planning_advice: Optional[str] = None,
    images_include_count: int = 2,
) -> Dict[str, Any]:
    """Run one standard planning turn and return the parsed planning response."""
    adapter = model_runtime.adapter
    planning_protocol = adapter.planning_protocol

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
            locate_result_codec.prompt_spec if include_locate_in_planning and locate_result_codec else None
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

    instruction: List[Dict[str, Any]] = [
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

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *instruction,
        *history_log,
    ]

    action_output_protocol = planning_protocol["action_output_protocol"]

    async def call_ai(retry_attempt: int, previous_parse_error: Optional[Any] = None):
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_parse_error),
            model_runtime,
            {
                "requiresOriginalImageDetail": include_locate_in_planning,
                "semanticRetryAttempt": retry_attempt,
            },
        )

    def parse_response(response: Dict[str, Any]) -> Dict[str, Any]:
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
        if plan_from_ai.get("action") and plan_from_ai.get("finalize_success") is not None:
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

    def to_parse_error(parse_error: Any, response: Dict[str, Any]) -> AIResponseParseError:
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

    response: Dict[str, Any] = result["response"]
    plan_from_ai: Dict[str, Any] = result["plan_from_ai"]
    actions: List[Dict[str, Any]] = result["actions"]
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

    yaml_flow = build_yaml_flow_from_plans(actions)

    return {
        **plan_from_ai,
        "actions": actions,
        "raw_response": raw_response,
        "usage": usage,
        "reasoning_content": reasoning_content,
        "yaml_flow": yaml_flow,
        "should_continue_planning": should_continue_planning,
    }


def _merge_sub_goals(history: ConversationHistory, update_sub_goals: List[Dict[str, Any]]) -> None:
    for goal in update_sub_goals:
        existing = next(
            (g for g in history.sub_goals if g["index"] == goal["index"]), None
        )
        if existing:
            existing["description"] = goal.get("description", existing["description"])
            existing["status"] = goal.get("status", existing["status"])
        else:
            history.sub_goals.append(dict(goal))


def build_yaml_flow_from_plans(actions: List[Dict[str, Any]]) -> str:
    """Serialize planned actions as a YAML workflow string (for cache/dump)."""
    import yaml

    flow = [
        {"type": action["type"], **(action.get("param") or {})} for action in actions
    ]
    return yaml.dump(flow, allow_unicode=True, sort_keys=False, width=10**6).strip()
