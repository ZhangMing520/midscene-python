"""Standard planning protocol types (upstream model-adapter/planning-protocol.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict


class PlanningActionOutputBuildInput(TypedDict, total=False):
    actionName: str
    param: dict[str, Any]
    locateFields: list[str]
    locateResultKey: str


class PlanningActionOutputProtocol(TypedDict):
    action_output_tag_names: list[str]
    action_output_rules: str
    action_output_placeholder: str
    build_action_output: Callable[[PlanningActionOutputBuildInput], str]
    parse_action_output: Callable[[str, list[Any]], dict[str, Any] | None]
    parse_raw_locate_parameter: Callable[[Any], Any]


class PlanningActionSpaceProtocol(TypedDict, total=False):
    title: str
    format: str
    include_action_output_example: bool
    build_locate_field_description: Callable[[dict[str, Any] | None], str]
    build_action_description: Callable[[dict[str, Any]], dict[str, Any]]


class StandardPlanningProtocol(TypedDict):
    response_prefix: str | None
    action_space_protocol: PlanningActionSpaceProtocol
    action_output_protocol: PlanningActionOutputProtocol


__all__ = [
    "PlanningActionOutputBuildInput",
    "PlanningActionOutputProtocol",
    "PlanningActionSpaceProtocol",
    "StandardPlanningProtocol",
]
