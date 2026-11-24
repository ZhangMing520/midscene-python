"""Access a task's service dump and search area (upstream dump/task-service-dump.ts)."""

from typing import Any


def _get(value: Any, name: str, snake_name: str | None = None) -> Any:
    if isinstance(value, dict):
        if name in value:
            return value[name]
        if snake_name and snake_name in value:
            return value[snake_name]
        return None
    if hasattr(value, name):
        return getattr(value, name)
    if snake_name and hasattr(value, snake_name):
        return getattr(value, snake_name)
    return None


def _is_record(value: Any) -> bool:
    return isinstance(value, dict) or (value is not None and hasattr(value, "__dict__"))


def _is_service_dump(value: Any) -> bool:
    if not _is_record(value):
        return False
    task_info = _get(value, "taskInfo", "task_info")
    return isinstance(_get(value, "type"), str) and _is_record(task_info)


def get_task_service_dump(task: Any = None) -> dict[str, Any] | None:
    """Return ``task.log.dump`` when it is a ServiceDump."""
    log = _get(task, "log") if task is not None else None
    dump = _get(log, "dump") if log is not None else None
    if _is_service_dump(dump):
        return dump
    return None


def get_task_search_area(task: Any = None) -> dict[str, Any] | None:
    """Return the explicit task search area, else the service dump's."""
    if task is None:
        return None
    search_area = _get(task, "searchArea", "search_area")
    if search_area is not None:
        return search_area
    dump = get_task_service_dump(task)
    task_info = _get(dump, "taskInfo", "task_info") if dump else None
    return _get(task_info, "searchArea", "search_area") if task_info else None


__all__ = ["get_task_search_area", "get_task_service_dump"]
