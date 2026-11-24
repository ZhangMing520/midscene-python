"""Custom planning definition types (upstream model-adapter/custom-planning-types.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict


class CustomPlanningMessageConfig(TypedDict, total=False):
    system_prompt_placement: str
    build_system_prompt: Callable[..., str]
    build_user_instruction: Callable[[str], str]
    build_assistant_content: Callable[[dict[str, Any], str], str]
    history_image_limit: int


class CustomPlanningDefinition(TypedDict, total=False):
    messages: CustomPlanningMessageConfig
    coordinates: dict[str, Any]
    parse_response: Callable[[str, Any, Any], dict[str, Any]]
    transform_actions: Callable[
        [dict[str, Any], Any, list[Any], Any], list[dict[str, Any]]
    ]
    should_continue_planning: Callable[[dict[str, Any], list[dict[str, Any]]], bool]
    build_response_log: Callable[[dict[str, Any], str], Any]


__all__ = ["CustomPlanningDefinition", "CustomPlanningMessageConfig"]
