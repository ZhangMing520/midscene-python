"""Standard planning protocol types (upstream model-adapter/planning-protocol.ts)."""

from collections.abc import Callable, Sequence
from typing import Any, TypedDict

JsonParser = Callable[..., Any]
ParsePlanningActionOutput = Callable[[str, list[Any] | None], dict[str, Any] | None]


class PlanningActionOutputBuildInput(TypedDict, total=False):
    actionName: str
    param: dict[str, Any]
    locateFields: list[str]
    locateResultKey: str | None


ActionOutputBuilder = Callable[[PlanningActionOutputBuildInput], str]


class PlanningActionOutputProtocol(TypedDict):
    action_output_tag_names: Sequence[str]
    action_output_rules: str
    action_output_placeholder: str
    build_action_output: Callable[[PlanningActionOutputBuildInput], str]
    parse_action_output: ParsePlanningActionOutput
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
