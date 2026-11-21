"""Custom planning definition types (upstream model-adapter/custom-planning-types.ts)."""

from typing import Any, Callable, Dict, List, TypedDict


class CustomPlanningMessageConfig(TypedDict, total=False):
    system_prompt_placement: str
    build_system_prompt: Callable[..., str]
    build_user_instruction: Callable[[str], str]
    build_assistant_content: Callable[[Dict[str, Any], str], str]
    history_image_limit: int


class CustomPlanningDefinition(TypedDict, total=False):
    messages: CustomPlanningMessageConfig
    coordinates: Dict[str, Any]
    parse_response: Callable[[str, Any, Any], Dict[str, Any]]
    transform_actions: Callable[
        [Dict[str, Any], Any, List[Any], Any], List[Dict[str, Any]]
    ]
    should_continue_planning: Callable[
        [Dict[str, Any], List[Dict[str, Any]]], bool
    ]
    build_response_log: Callable[[Dict[str, Any], str], Any]


__all__ = ["CustomPlanningDefinition", "CustomPlanningMessageConfig"]
