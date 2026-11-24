"""Planning workflow types (upstream workflows/planning/types.ts)."""

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict


class PlanOptions(TypedDict, total=False):
    ui_context: Any
    action_space: list[Any]
    action_context: str | None
    planning_advice: str | None
    model_runtime: Any
    get_default_model_runtime: Callable[[], Any] | None
    conversation_history: Any
    include_locate_in_planning: bool
    images_include_count: int | None
    effort: str
    abort_signal: Any


class PlanningAIResponse(TypedDict, total=False):
    actions: list[dict[str, Any]]
    action: dict[str, Any]
    log: str
    memory: str
    error: str
    thought: str
    finalize_success: bool
    finalize_message: str
    update_sub_goals: list[dict[str, Any]]
    mark_finished_indexes: list[int]
    delegation: bool
    raw_response: str
    usage: dict[str, Any] | None
    reasoning_content: str | None
    yaml_flow: str
    should_continue_planning: bool


PlanFn = Callable[[Any, PlanOptions], Awaitable[PlanningAIResponse]]


__all__ = ["PlanFn", "PlanOptions", "PlanningAIResponse"]
