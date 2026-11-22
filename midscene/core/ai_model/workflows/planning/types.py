"""Planning workflow types (upstream workflows/planning/types.ts)."""

from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict


class PlanOptions(TypedDict, total=False):
    ui_context: Any
    action_space: List[Any]
    action_context: Optional[str]
    planning_advice: Optional[str]
    model_runtime: Any
    get_default_model_runtime: Optional[Callable[[], Any]]
    conversation_history: Any
    include_locate_in_planning: bool
    images_include_count: Optional[int]
    effort: str
    abort_signal: Any


class PlanningAIResponse(TypedDict, total=False):
    actions: List[Dict[str, Any]]
    action: Dict[str, Any]
    log: str
    memory: str
    error: str
    thought: str
    finalize_success: bool
    finalize_message: str
    update_sub_goals: List[Dict[str, Any]]
    mark_finished_indexes: List[int]
    delegation: bool
    raw_response: str
    usage: Optional[Dict[str, Any]]
    reasoning_content: Optional[str]
    yaml_flow: str
    should_continue_planning: bool


PlanFn = Callable[[Any, PlanOptions], Awaitable[PlanningAIResponse]]


__all__ = ["PlanFn", "PlanOptions", "PlanningAIResponse"]
