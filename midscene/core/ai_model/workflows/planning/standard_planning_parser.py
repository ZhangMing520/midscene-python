"""Standard planning response parser (upstream workflows/planning/standard-planning-parser.ts)."""

import re
from collections.abc import Sequence
from typing import Any

from midscene.core.ai_model.model_adapter.planning_protocol import (
    PlanningActionOutputProtocol,
)
from midscene.core.ai_model.shared.xml import (
    extract_raw_xml_fragment,
    extract_xml_tag,
)
from midscene.core.ai_model.workflows.planning.planning_action_log import (
    _build_non_action_planning_log,
    build_planning_action_log,
)

_SUB_GOAL_RE = re.compile(
    r'<sub-goal\s+index="(\d+)"\s+status="(pending|finished)"(?:\s*/>|>([\s\S]*?)</sub-goal>)',
    re.IGNORECASE,
)
_MARK_SUB_GOAL_DONE_RE = re.compile(
    r'<sub-goal\s+index="(\d+)"\s+status="finished"\s*/>', re.IGNORECASE
)
_COMPLETE_RE = re.compile(
    r'<complete\s+success="(true|false)">([\s\S]*?)</complete>', re.IGNORECASE
)


def parse_sub_goals_from_xml(xml_content: str) -> list[dict[str, Any]]:
    sub_goals: list[dict[str, Any]] = []
    for match in _SUB_GOAL_RE.finditer(xml_content):
        sub_goals.append(
            {
                "index": int(match.group(1)),
                "status": match.group(2),
                "description": (match.group(3) or "").strip(),
            }
        )
    return sub_goals


def parse_mark_finished_indexes(xml_content: str) -> list[int]:
    return [
        int(match.group(1)) for match in _MARK_SUB_GOAL_DONE_RE.finditer(xml_content)
    ]


def parse_xml_planning_response(
    xml_string: str,
    action_output_tag_names: Sequence[str],
    include_thought: bool,
) -> tuple[dict[str, Any], str]:
    """Parse common XML fields and retain the raw action-protocol XML."""
    thought = extract_xml_tag(xml_string, "planning") if include_thought else None
    memory = extract_xml_tag(xml_string, "memory")
    log = extract_xml_tag(xml_string, "log") or ""
    error = extract_xml_tag(xml_string, "error")

    complete_match = _COMPLETE_RE.search(xml_string)
    finalize_message: str | None = None
    finalize_success: bool | None = None
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

    parsed: dict[str, Any] = {"log": log}
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


def parse_standard_planning_response(
    xml_string: str,
    action_output_protocol: PlanningActionOutputProtocol,
    action_space: list[Any],
    include_thought: bool,
    log_source: str = "model",
) -> dict[str, Any]:
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


__all__ = [
    "parse_mark_finished_indexes",
    "parse_standard_planning_response",
    "parse_sub_goals_from_xml",
    "parse_xml_planning_response",
]
