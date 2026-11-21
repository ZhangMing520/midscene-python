"""Action task metadata (upstream agent/tasks.ts)."""

from typing import Any, Dict, Optional

from midscene.core.agent.utils import _strip_runtime_locate_result
from midscene.core.dump import build_execution_task


def action_progress_summary(action: Dict[str, Any]) -> Dict[str, Any]:
    """Structured, presentation-free action descriptor for progress events."""
    name = action.get("type")
    param = action.get("param") or {}
    summary: Dict[str, Any] = {"name": name}
    locate = param.get("locate") or param.get("from")
    if isinstance(locate, dict):
        if locate.get("prompt"):
            summary["target"] = locate["prompt"]
        bbox = locate.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            summary["bbox"] = [int(v) for v in bbox[:4]]
    elif isinstance(locate, str):
        summary["target"] = locate
    if "target" not in summary and isinstance(param.get("prompt"), str):
        summary["target"] = param["prompt"]
    if "target" not in summary and "bbox" not in summary:
        compact = {
            key: value
            for key, value in param.items()
            if isinstance(value, (str, int, float, bool))
        }
        if compact:
            summary["param"] = compact
    return summary


def build_action_report_task(
    action: Dict[str, Any],
    started_at: float,
    finished_at: float,
    status: str = "finished",
    error: Optional[BaseException] = None,
) -> Dict[str, Any]:
    """Build one Action Space execution task for the report dump."""
    task = build_execution_task(
        "Action Space",
        action.get("type"),
        _strip_runtime_locate_result(action.get("param") or {}),
        status=status,
        timing={
            "start": int(started_at * 1000),
            "end": int(finished_at * 1000),
            "cost": int((finished_at - started_at) * 1000),
        },
    )
    if error is not None:
        task["errorMessage"] = str(error)
    return task
