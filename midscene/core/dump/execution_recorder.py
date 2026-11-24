"""Execution record keeping (upstream dump/execution-recorder.ts).

The Python SDK keeps executions in memory until the report is flushed, so the
recorder only tracks the latest state of every execution by id (or object
identity for anonymous executions).
"""

import time
from collections.abc import Mapping
from typing import Any

from midscene.core.dump.report_action_dump import ExecutionDump, ReportActionDump


class ExecutionRecorder:
    """Keep the latest state of each execution."""

    def __init__(self, executions: list[dict[str, Any]] | None = None) -> None:
        self._executions: list[dict[str, Any]] = (
            executions if executions is not None else []
        )
        self._index_by_key: dict[str, int] = {}
        self.report_meta: Mapping[str, Any] | None = None

    @property
    def executions(self) -> list[dict[str, Any]]:
        return self._executions

    def record(
        self,
        execution: dict[str, Any],
        meta: Mapping[str, Any] | None = None,
    ) -> str:
        """Store an execution, replacing any previous state with the same key."""
        if meta is not None:
            self.report_meta = meta
        key = self._execution_key(execution)
        index = self._index_by_key.get(key)
        if index is None:
            self._executions.append(execution)
            self._index_by_key[key] = len(self._executions) - 1
        else:
            self._executions[index] = execution
        return key

    def to_dump(self, meta: dict[str, Any] | None = None) -> ReportActionDump:
        """Build a report dump from the recorded executions (upstream toDump)."""
        resolved_meta = meta if meta is not None else self.report_meta
        if resolved_meta is None:
            raise ValueError("Cannot create a report without execution metadata")
        return ReportActionDump({**resolved_meta, "executions": self._executions})

    def capture(
        self,
        execution_ids: list[str] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Freeze executions + screenshots (upstream capture)."""
        selected = set(execution_ids) if execution_ids is not None else None
        executions = [
            execution
            for execution in self._executions
            if selected is None
            or (
                isinstance(execution, dict)
                and execution.get("id")
                and execution["id"] in selected
            )
        ]
        resolved_meta = meta if meta is not None else self.report_meta
        if resolved_meta is None:
            raise ValueError("Cannot capture a report without execution metadata")

        screenshots: list[Any] = []
        reference_urls: list[str] = []
        for execution in executions:
            dump_execution = (
                execution
                if isinstance(execution, ExecutionDump)
                else ExecutionDump.from_json(execution)
            )
            screenshots.extend(dump_execution.collect_screenshots())
            reference_urls.extend(dump_execution.get_reference_image_urls())

        frozen = ReportActionDump({**resolved_meta, "executions": executions})
        dump = frozen.from_serialized_string(frozen.serialize())
        return {
            "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z",
            "dump": dump,
            "screenshots": screenshots,
            "referenceImageUrls": list(dict.fromkeys(reference_urls)),
        }

    def clear(self) -> None:
        self._executions.clear()
        self._index_by_key.clear()
        self.report_meta = None

    @staticmethod
    def _execution_key(execution: dict[str, Any]) -> str:
        execution_id = execution.get("id")
        if execution_id:
            return f"id:{execution_id}"
        # Upstream keeps anonymous executions in a WeakMap keyed by object.
        return f"obj:{id(execution)}"


__all__ = ["ExecutionRecorder"]
