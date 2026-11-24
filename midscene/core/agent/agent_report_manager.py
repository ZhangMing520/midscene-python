"""Report helper functions (upstream agent/agent-report-manager.ts + record-to-report.ts)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

if TYPE_CHECKING:
    from midscene.core.dump import ExecutionDumpBuilder
    from midscene.core.dump.report_artifact_store import ReportArtifactStore
    from midscene.core.types import InterfaceType


DumpUpdateListener = Callable[[str, dict[str, Any] | None], object]


class _HasToDict(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class _ReportOptions(Protocol):
    group_name: str
    group_description: str
    report_attributes: dict[str, Any] | None
    report_artifact_dir: str | None


class _ReportAgent(Protocol):
    options: _ReportOptions
    interface_type: InterfaceType | str
    destroyed: bool
    _report_builder: ExecutionDumpBuilder | None
    _report_finalized: str | None
    _report_file_name: str | None
    _report_artifact_store: ReportArtifactStore | None
    _last_execution: dict[str, Any] | None
    _execution_index_by_runner: dict[int, int]
    _dump_update_listeners: list[DumpUpdateListener]

    def _check_not_destroyed(self) -> None: ...

    def _get_report_builder(self) -> ExecutionDumpBuilder: ...

    def _report_name(self) -> str: ...

    def _write_report_artifact(self, name: str, dump: dict[str, Any]) -> None: ...

    async def finalize_report(self) -> str | None: ...

    async def flush_report(self) -> str | None: ...

    def dump_data_string(self, opt: dict[str, Any] | None = None) -> str: ...

    def remove_dump_update_listener(self, listener: DumpUpdateListener) -> None: ...


def get_report_builder(agent: _ReportAgent) -> ExecutionDumpBuilder:
    if agent._report_builder is None:
        from midscene.core.dump import ExecutionDumpBuilder

        tag = getattr(agent.interface_type, "value", agent.interface_type)
        agent._report_builder = ExecutionDumpBuilder(
            group_name=getattr(agent.options, "group_name", "Midscene Report"),
            group_description=getattr(agent.options, "group_description", ""),
            device_type=tag,
        )
        attributes = getattr(agent.options, "report_attributes", None)
        if attributes:
            agent._report_builder.dump.update(attributes)
    return agent._report_builder


async def flush_report(
    agent: _ReportAgent,
) -> str | None:
    """Write the in-memory report to disk; returns the report path."""
    if agent._report_builder is None:
        return None
    name = agent._report_name()
    json_path = agent._report_builder.write_to_disk(name)
    from midscene.core.report import write_report_html

    dump = agent._report_builder.to_dict()
    html_path = write_report_html(dump, name)
    agent._write_report_artifact(name, dump)
    return html_path or json_path or None


def write_report_artifact(agent: _ReportAgent, name: str, dump: dict[str, Any]) -> None:
    """Mirror the report into a directory artifact when configured.

    Artifact publishing is secondary to the single-file report: a failure
    here must not make ai_act / destroy fail.
    """
    artifact_dir = getattr(agent.options, "report_artifact_dir", None)
    if not artifact_dir:
        return
    from midscene.shared.report_artifact import ReportArtifactStore

    try:
        if agent._report_artifact_store is None:
            report_id = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(name).stem).strip("-")
            agent._report_artifact_store = ReportArtifactStore(
                artifact_dir,
                report_id or "report",
                reuse_existing_report=True,
            )
        agent._report_artifact_store.write_execution(name, dump, {"reportName": name})
    except Exception as error:
        logger.warning(f"Failed to write report artifact to {artifact_dir}: {error}")


async def reset_dump(
    agent: _ReportAgent,
) -> dict[str, Any]:
    """Finalize the preceding report and start a fresh execution dump."""
    agent._check_not_destroyed()
    try:
        await agent.finalize_report()
    except Exception as e:  # failure belongs to the previous report
        logger.warning(f"Failed to finalize previous report; resetting dump: {e}")
    agent._check_not_destroyed()
    agent._report_builder = None
    agent._report_finalized = None
    agent._report_file_name = None
    agent._last_execution = None
    agent._execution_index_by_runner = {}
    return agent._get_report_builder().to_dict()


async def finalize_report(
    agent: _ReportAgent,
) -> str | None:
    """Seal the current report and release its in-memory records."""
    if agent._report_finalized is not None:
        return agent._report_finalized or None
    if agent.destroyed:
        raise RuntimeError("Cannot finalize a report using a destroyed Agent.")
    path = await agent.flush_report()
    agent._report_finalized = path or ""
    # Mirror upstream clearDumpInMemory: records are released after sealing.
    agent._report_builder = None
    agent._last_execution = None
    agent._execution_index_by_runner = {}
    return path


def append_execution_dump(
    agent: _ReportAgent, execution: dict[str, Any], runner: object | None = None
) -> None:
    """Append one execution dump; a runner replaces its previous entry."""
    if agent._report_finalized is not None:
        raise RuntimeError(
            "Cannot append to a finalized report. Await resetDump() first."
        )
    builder = agent._get_report_builder()
    executions = builder.dump["executions"]
    if runner is not None:
        key = id(runner)
        index = agent._execution_index_by_runner.get(key)
        if index is not None:
            executions[index] = execution
        else:
            executions.append(execution)
            agent._execution_index_by_runner[key] = len(executions) - 1
    else:
        executions.append(execution)
    agent._last_execution = execution


def dump_data_string(agent: _ReportAgent, opt: dict[str, Any] | None = None) -> str:
    """Serialize the in-memory dump (upstream dumpDataString)."""
    return json.dumps(
        agent._get_report_builder().to_dict(),
        ensure_ascii=False,
    )


def report_html_string(agent: _ReportAgent, opt: dict[str, Any] | None = None) -> str:
    """Render the in-memory dump as a self-contained HTML string."""
    from midscene.core.report_html_template import render_report_html

    return render_report_html(
        agent._get_report_builder().to_dict(), agent._report_name()
    )


def write_out_action_dumps(
    agent: _ReportAgent, execution_dump: dict[str, Any] | None = None
) -> str | None:
    """Persist the current report (JSON + HTML) without disposing the Agent."""
    if agent._report_finalized is not None:
        if execution_dump is not None:
            raise RuntimeError(
                "Cannot append to a finalized report. Await resetDump() first."
            )
        return agent._report_finalized or None
    if execution_dump is not None:
        agent._last_execution = execution_dump
    name = agent._report_name()
    json_path = agent._get_report_builder().write_to_disk(name)
    from midscene.core.report import write_report_html

    html_path = write_report_html(agent._get_report_builder().to_dict(), name)
    return html_path or json_path or None


def add_dump_update_listener(
    agent: _ReportAgent, listener: DumpUpdateListener
) -> Callable[[], None]:
    """Subscribe to dump updates; returns a remove function."""
    agent._dump_update_listeners.append(listener)

    def remove() -> None:
        agent.remove_dump_update_listener(listener)

    return remove


def remove_dump_update_listener(
    agent: _ReportAgent, listener: DumpUpdateListener
) -> None:
    try:
        agent._dump_update_listeners.remove(listener)
    except ValueError:
        pass


def clear_dump_update_listeners(
    agent: _ReportAgent,
) -> None:
    agent._dump_update_listeners.clear()


def notify_dump_update_listeners(
    agent: _ReportAgent, execution: dict[str, Any] | None = None
) -> None:
    if not agent._dump_update_listeners:
        return
    dump_string = agent.dump_data_string()
    for listener in list(agent._dump_update_listeners):
        try:
            result = listener(dump_string, execution)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as e:  # listeners must never break execution
            logger.warning(f"dump update listener threw, ignoring: {e}")


class AgentReportManager:
    """Own report state and persistence (upstream AgentReportManager).

    The Python port keeps report state on the Agent; this facade exposes the
    upstream manager surface on top of the existing module-level helpers.
    """

    def __init__(
        self, agent: _ReportAgent | None = None, context: _ReportAgent | None = None
    ) -> None:
        resolved = agent if agent is not None else context
        if resolved is None:
            raise ValueError("AgentReportManager requires an agent")
        self.agent: _ReportAgent = resolved
        self._report_file: str | None = None
        self._report_file_name: str | None = getattr(
            self.agent, "_report_file_name", None
        )
        self._report_by_runner: dict[int, AgentReportManager] = {}
        self._active_operations: set[asyncio.Future[Any]] = set()
        self._report_reset: asyncio.Future[dict[str, Any]] | None = None

    @property
    def dump(self) -> dict[str, Any]:
        return get_report_builder(self.agent).to_dict()

    @dump.setter
    def dump(self, value: dict[str, Any] | _HasToDict) -> None:
        builder = get_report_builder(self.agent)
        builder.dump = (
            cast(_HasToDict, value).to_dict() if hasattr(value, "to_dict") else value
        )

    @property
    def report_file(self) -> str | None:
        if self._report_file is not None:
            return self._report_file
        return getattr(self.agent, "_report_finalized", None) or None

    @report_file.setter
    def report_file(self, value: str | None) -> None:
        self._report_file = value

    @property
    def report_file_name(self) -> str | None:
        return self._report_file_name

    @report_file_name.setter
    def report_file_name(self, value: str | None) -> None:
        self._report_file_name = value
        self.agent._report_file_name = value

    def assert_report_writable(self) -> _ReportAgent:
        if getattr(self.agent, "destroyed", False):
            raise RuntimeError("Cannot execute using a destroyed Agent.")
        if self._report_reset is not None:
            raise RuntimeError("Report reset is in progress. Await resetDump() first.")
        if getattr(self.agent, "_report_finalized", None) is not None:
            raise RuntimeError(
                "The report has been finalized. Call and await resetDump() "
                "before executing again."
            )
        return self.agent

    async def with_report_operation(
        self, operation: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Run an operation while it counts as an active report write."""
        self.assert_report_writable()
        pending = asyncio.ensure_future(operation())
        self._active_operations.add(pending)
        try:
            return await pending
        finally:
            self._active_operations.discard(pending)

    async def reset_dump(self) -> dict[str, Any]:
        if self._report_reset is not None:
            return await self._report_reset

        async def run() -> dict[str, Any]:
            result = await reset_dump(self.agent)
            self._report_file = None
            self._report_file_name = getattr(self.agent, "_report_file_name", None)
            return result

        self._report_reset = asyncio.ensure_future(run())
        try:
            return await self._report_reset
        finally:
            self._report_reset = None

    async def finalize_report(self) -> str | None:
        path = await finalize_report(self.agent)
        self._report_file = path
        return path

    def append_execution_dump(
        self, execution: dict[str, Any], runner: object | None = None
    ) -> None:
        append_execution_dump(self.agent, execution, runner)

    def dump_data_string(self, opt: dict[str, Any] | None = None) -> str:
        return dump_data_string(self.agent, opt)

    def report_html_string(self, get_dump_string: Any = None) -> str:
        return report_html_string(self.agent)

    def write_out_action_dumps(
        self, execution_dump: dict[str, Any] | None = None
    ) -> str | None:
        return write_out_action_dumps(self.agent, execution_dump)

    async def flush_report(self) -> str | None:
        return await flush_report(self.agent)

    def add_dump_update_listener(
        self, listener: DumpUpdateListener
    ) -> Callable[[], None]:
        return add_dump_update_listener(self.agent, listener)

    def remove_dump_update_listener(self, listener: DumpUpdateListener) -> None:
        remove_dump_update_listener(self.agent, listener)

    def clear_dump_update_listeners(self) -> None:
        clear_dump_update_listeners(self.agent)

    def notify_dump_update_listeners(
        self, execution_dump: dict[str, Any] | None = None
    ) -> None:
        notify_dump_update_listeners(self.agent, execution_dump)

    def bind_runner(self, runner: object) -> None:
        self._report_by_runner[id(runner)] = self

    def assert_runner_current(self, runner: object) -> None:
        bound = self._report_by_runner.get(id(runner))
        if (
            bound is not self
            or getattr(self.agent, "_report_finalized", None) is not None
        ):
            raise RuntimeError(
                "Cannot write a late execution update into a different or "
                "finalized report."
            )

    async def flush_pending_writes(self) -> None:
        if getattr(self.agent, "_report_builder", None) is None:
            return
        await self.flush_report()

    async def wait_for_operations(self) -> None:
        while self._active_operations:
            await asyncio.gather(*list(self._active_operations), return_exceptions=True)

    async def wait_for_reset(self) -> None:
        if self._report_reset is not None:
            await asyncio.gather(self._report_reset, return_exceptions=True)


__all__ = [
    "AgentReportManager",
    "add_dump_update_listener",
    "append_execution_dump",
    "clear_dump_update_listeners",
    "dump_data_string",
    "finalize_report",
    "flush_report",
    "get_report_builder",
    "notify_dump_update_listeners",
    "remove_dump_update_listener",
    "report_html_string",
    "reset_dump",
    "write_out_action_dumps",
    "write_report_artifact",
]
