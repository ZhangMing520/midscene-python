"""Execution record keeping (upstream dump/execution-recorder.ts).

The Python SDK keeps executions in memory until the report is flushed, so the
recorder only tracks the latest state of every execution by id (or object
identity for anonymous executions).
"""

from typing import Any, Dict, List, Optional


class ExecutionRecorder:
    """Keep the latest state of each execution."""

    def __init__(
        self, executions: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        self._executions: List[Dict[str, Any]] = (
            executions if executions is not None else []
        )
        self._index_by_key: Dict[str, int] = {}

    @property
    def executions(self) -> List[Dict[str, Any]]:
        return self._executions

    def record(self, execution: Dict[str, Any]) -> str:
        """Store an execution, replacing any previous state with the same key."""
        key = self._execution_key(execution)
        index = self._index_by_key.get(key)
        if index is None:
            self._executions.append(execution)
            self._index_by_key[key] = len(self._executions) - 1
        else:
            self._executions[index] = execution
        return key

    def clear(self) -> None:
        self._executions.clear()
        self._index_by_key.clear()

    @staticmethod
    def _execution_key(execution: Dict[str, Any]) -> str:
        execution_id = execution.get("id")
        if execution_id:
            return f"id:{execution_id}"
        # Upstream keeps anonymous executions in a WeakMap keyed by object.
        return f"obj:{id(execution)}"


__all__ = ["ExecutionRecorder"]
