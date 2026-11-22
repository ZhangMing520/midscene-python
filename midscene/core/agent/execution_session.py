"""Execution session lifecycle (upstream core/src/agent/execution-session.ts).

A thin wrapper around :class:`TaskRunner` that represents a single linear
execution run.
"""

from typing import Any, Dict, List, Optional, Union

from midscene.core.task_runner import TaskRunner


class ExecutionSession:
    """Run one linear batch of execution tasks through a ``TaskRunner``."""

    def __init__(
        self,
        name: str,
        ui_context_builder: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._runner = TaskRunner(name, ui_context_builder, options)

    async def append(
        self,
        tasks: Union[Dict[str, Any], List[Dict[str, Any]]],
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._runner.append(tasks, options)

    async def append_and_run(
        self,
        tasks: Union[Dict[str, Any], List[Dict[str, Any]]],
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return await self._runner.append_and_flush(tasks, options)

    async def run(
        self, options: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return await self._runner.flush(options)

    def is_in_error_state(self) -> bool:
        return self._runner.is_in_error_state()

    def latest_error_task(self) -> Optional[Dict[str, Any]]:
        return self._runner.latest_error_task()

    async def append_error_plan(self, error_msg: str) -> Dict[str, Any]:
        return await self._runner.append_error_plan(error_msg)

    def get_runner(self) -> TaskRunner:
        return self._runner


__all__ = ["ExecutionSession"]
