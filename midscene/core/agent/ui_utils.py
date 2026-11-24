"""UI coordinate helpers (upstream agent/ui-utils.ts)."""

from typing import Any

from midscene.core.types import UIContext


def type_str(task: dict[str, Any]) -> str:
    """Task type label (upstream typeStr)."""
    from midscene.core.report_markdown import _type_str

    return _type_str(task)


def locate_param_str(locate: Any) -> str:
    """Human-readable locate prompt (upstream locateParamStr)."""
    from midscene.core.report_markdown import _locate_param_str

    return _locate_param_str(locate)


def scroll_param_str(scroll_param: Any) -> str:
    """Human-readable scroll parameters (upstream scrollParamStr)."""
    from midscene.core.report_markdown import _scroll_param_str

    return _scroll_param_str(scroll_param)


def pull_param_str(pull_param: Any) -> str:
    """Human-readable pull parameters (upstream pullParamStr)."""
    from midscene.core.report_markdown import _pull_param_str

    return _pull_param_str(pull_param)


def extract_insight_param(task_param: Any) -> dict[str, Any]:
    """Extract insight content/images (upstream extractInsightParam)."""
    from midscene.core.report_markdown import _extract_insight_param

    return _extract_insight_param(task_param)


def task_title_str(task_type: str, prompt: str) -> str:
    """Task title used by the report timeline (upstream taskTitleStr)."""
    return f"{task_type} - {prompt}" if prompt else task_type


def param_str(task: dict[str, Any]) -> str:
    """Human-readable task parameters (upstream paramStr)."""
    from midscene.core.report_markdown import _param_str

    return _param_str(task)


def to_logical_coords(element: dict[str, Any], context: UIContext) -> dict[str, Any]:
    """Scale screenshot-space coordinates back to logical viewport space
    (upstream task-builder.ts divides the shot coordinates by
    shrunkShotToLogicalRatio)."""
    ratio = float(getattr(context, "shrunk_shot_to_logical_ratio", 1.0) or 1.0)
    if ratio == 1.0:
        return element
    center = element.get("center")
    if center:
        element = {
            **element,
            "center": [center[0] / ratio, center[1] / ratio],
        }
    rect = element.get("rect")
    if rect:
        element = {
            **element,
            "rect": {
                "left": rect["left"] / ratio,
                "top": rect["top"] / ratio,
                "width": rect["width"] / ratio,
                "height": rect["height"] / ratio,
            },
        }
    return element


__all__ = [
    "extract_insight_param",
    "locate_param_str",
    "param_str",
    "pull_param_str",
    "scroll_param_str",
    "task_title_str",
    "to_logical_coords",
    "type_str",
]
