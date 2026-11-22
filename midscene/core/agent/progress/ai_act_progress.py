"""Structured aiAct progress extraction (upstream progress/ai-act-progress.ts).

Turns a raw execution task into the structured action descriptor carried by
progress events. Formatting for display stays with consumers.
"""

import math
from typing import Any, Dict, Optional, Tuple

_MAX_COMPACT_STRING_LENGTH = 180
_LOCATOR_PARAM_KEYS = ("locate", "from", "to", "start", "end")


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _compact_progress_value(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str):
        if len(value) > _MAX_COMPACT_STRING_LENGTH:
            return f"{value[:_MAX_COMPACT_STRING_LENGTH - 3]}..."
        return value
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_compact_progress_value(item) for item in value[:5]]
    if _is_record(value) and isinstance(value.get("prompt"), str):
        return _compact_progress_value(value["prompt"])
    if not _is_record(value):
        return str(value)
    return {
        key: _compact_progress_value(entry)
        for key, entry in list(value.items())[:6]
    }


def _summarize_param(param: Any) -> Any:
    if not isinstance(param, dict):
        return _compact_progress_value(param)

    if isinstance(param.get("prompt"), str):
        return _compact_progress_value(param["prompt"])
    locate = param.get("locate")
    if isinstance(locate, dict):
        summary: Dict[str, Any] = {
            "locate": _compact_progress_value(locate.get("prompt"))
        }
        for key, value in list(param.items()):
            if key == "locate":
                continue
            summary[key] = _compact_progress_value(value)
            if len(summary) > 4:
                break
        return summary

    return _compact_progress_value(param)


def error_message_for_ai_act(error: Any) -> str:
    return str(error)


def _number(value: Any) -> Optional[float]:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return value
    return None


def _bbox_from_property(
    value: Dict[str, Any], key: str
) -> Optional[Tuple[float, float, float, float]]:
    bbox = value.get(key)
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    left, top, right, bottom = (_number(item) for item in bbox[:4])
    if None in (left, top, right, bottom):
        return None
    return (left, top, right, bottom)


def _point_from_locate_like(
    value: Dict[str, Any]
) -> Optional[Tuple[float, float]]:
    center = value.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        x, y = _number(center[0]), _number(center[1])
        if x is not None and y is not None:
            return (x, y)
    return None


def _bbox_from_locate_like(
    value: Dict[str, Any]
) -> Optional[Tuple[float, float, float, float]]:
    bbox = _bbox_from_property(value, "bbox")
    if bbox:
        return bbox

    rect = value.get("rect")
    if not isinstance(rect, dict):
        return None
    left = _number(rect.get("left"))
    top = _number(rect.get("top"))
    width = _number(rect.get("width"))
    height = _number(rect.get("height"))
    if None in (left, top, width, height):
        return None
    return (left, top, left + width, top + height)


def _target_text_from_locate_like(value: Dict[str, Any]) -> str:
    if isinstance(value.get("description"), str):
        return value["description"]
    if isinstance(value.get("prompt"), str):
        return value["prompt"]
    return ""


def _is_locate_like(value: Any) -> bool:
    if not _is_record(value):
        return False
    return any(
        key in value
        for key in (
            "locatedPixelResult",
            "center",
            "rect",
            "point",
            "bbox",
            "prompt",
            "description",
        )
    )


def _first_locate_like_param(param: Any) -> Optional[Dict[str, Any]]:
    if not _is_record(param):
        return None
    for key in _LOCATOR_PARAM_KEYS:
        value = param.get(key)
        if _is_locate_like(value):
            return value
    for value in param.values():
        if _is_locate_like(value):
            return value
    return None


def _has_unresolved_locate_like_param(param: Any) -> bool:
    if not _is_record(param):
        return False
    for key, value in param.items():
        if key in _LOCATOR_PARAM_KEYS and isinstance(value, str):
            return True
        if _is_locate_like(value) and not _point_from_locate_like(value):
            return True
    return False


def extract_progress_action(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract the structured action descriptor for an Action Space task."""
    if (
        task.get("type") != "Action Space"
        or task.get("subType") in ("Finished", "Error")
    ):
        return None

    sub_type = task.get("subType")
    name = sub_type if isinstance(sub_type, str) and sub_type else "Action"

    locate = _first_locate_like_param(task.get("param"))
    if locate:
        point = _point_from_locate_like(locate)
        if point:
            action: Dict[str, Any] = {"name": name, "point": point}
            target = _target_text_from_locate_like(locate)
            if target:
                action["target"] = target
            bbox = _bbox_from_locate_like(locate)
            if bbox:
                action["bbox"] = bbox
            return action

    # A locate-like param that has not resolved to a center is not reportable
    # yet; skip it so consumers never render a half-resolved action.
    if _has_unresolved_locate_like_param(task.get("param")):
        return None

    param = _summarize_param(task.get("param"))
    action = {"name": name}
    if param is not None and param != "":
        action["param"] = param
    return action


def create_ai_act_action_reporter(plan_index: int, plan_limit: int, emit):
    """Map runner task-lifecycle events to aiAct action progress."""

    async def reporter(event: Dict[str, Any]) -> None:
        action = extract_progress_action(event.get("task") or {})
        if not action:
            return

        task = event.get("task") or {}
        base = {
            "planIndex": plan_index,
            "planLimit": plan_limit,
            "action": action,
        }
        duration_ms = (task.get("timing") or {}).get("cost")

        kind = event.get("kind")
        if kind == "start":
            await emit("plan_action", base)
            await emit("action_running", base)
        elif kind == "finish":
            await emit("action_done", {**base, "durationMs": duration_ms})
        elif kind == "error":
            await emit(
                "action_failed",
                {
                    **base,
                    "durationMs": duration_ms,
                    "error": task.get("errorMessage"),
                },
            )

    return reporter


__all__ = [
    "create_ai_act_action_reporter",
    "error_message_for_ai_act",
    "extract_progress_action",
]
