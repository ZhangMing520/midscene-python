"""Standard planning protocol types (upstream model-adapter/planning-protocol.ts)."""

from typing import Any, Callable, Dict, List, Optional, TypedDict


class PlanningActionOutputBuildInput(TypedDict, total=False):
    actionName: str
    param: Dict[str, Any]
    locateFields: List[str]
    locateResultKey: str


class PlanningActionOutputProtocol(TypedDict):
    action_output_tag_names: List[str]
    action_output_rules: str
    action_output_placeholder: str
    build_action_output: Callable[[PlanningActionOutputBuildInput], str]
    parse_action_output: Callable[[str, List[Any]], Optional[Dict[str, Any]]]
    parse_raw_locate_parameter: Callable[[Any], Any]


class PlanningActionSpaceProtocol(TypedDict, total=False):
    title: str
    format: str
    include_action_output_example: bool
    build_locate_field_description: Callable[[Optional[Dict[str, Any]]], str]
    build_action_description: Callable[[Dict[str, Any]], Dict[str, Any]]


class StandardPlanningProtocol(TypedDict):
    response_prefix: Optional[str]
    action_space_protocol: PlanningActionSpaceProtocol
    action_output_protocol: PlanningActionOutputProtocol


__all__ = [
    "PlanningActionOutputBuildInput",
    "PlanningActionOutputProtocol",
    "PlanningActionSpaceProtocol",
    "StandardPlanningProtocol",
]
