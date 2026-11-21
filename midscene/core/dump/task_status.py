"""Task status derivation (upstream dump/task-status.ts).

Pure functions over plain dump fields so report icons and merged-report
status aggregation agree on what "failed" means.
"""

from typing import Any, Iterable, Optional


def _field(task: Any, key: str, default: Any = None) -> Any:
    if isinstance(task, dict):
        return task.get(key, default)
    return getattr(task, key, default)


def derive_task_status(task: Any) -> str:
    """Derive one task's semantic status from its raw dump fields."""
    status = _field(task, "status")
    sub_type = _field(task, "subType", _field(task, "sub_type"))
    output = _field(task, "output")
    error = _field(task, "error")
    error_message = _field(task, "errorMessage", _field(task, "error_message"))
    is_finished = status == "finished"

    if status == "failed":
        return "failed"
    if is_finished and (error or error_message):
        return "failed"
    if is_finished and sub_type == "WaitFor" and output is False:
        return "warning"
    if sub_type == "Assert" and is_finished and output is False:
        return "failed"
    if status == "pending":
        return "pending"
    if status == "running":
        return "running"
    if status == "cancelled":
        return "cancelled"
    return "passed"


def derive_case_status(executions: Iterable[Any]) -> str:
    """Aggregate a case's executions; `failed` when any task derives failed."""
    for execution in executions or ():
        tasks = _field(execution, "tasks") or []
        for task in tasks:
            if derive_task_status(task) == "failed":
                return "failed"
    return "passed"


def task_status_error(task: Any) -> Optional[Any]:
    """Return the recorded failure for a task, if any."""
    if derive_task_status(task) != "failed":
        return None
    return _field(task, "error") or _field(task, "errorMessage", _field(task, "error_message"))


__all__ = ["derive_case_status", "derive_task_status", "task_status_error"]
