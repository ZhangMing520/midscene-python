"""Report helper functions (upstream agent/agent-report-manager.ts + record-to-report.ts)."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger


def get_report_builder(agent, ):
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


async def flush_report(agent, ) -> Optional[str]:
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


def write_report_artifact(agent, name: str, dump: Dict[str, Any]) -> None:
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
        agent._report_artifact_store.write_execution(
            name, dump, {"reportName": name}
        )
    except Exception as error:
        logger.warning(f"Failed to write report artifact to {artifact_dir}: {error}")


async def reset_dump(agent, ) -> Dict[str, Any]:
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


async def finalize_report(agent, ) -> Optional[str]:
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
    agent, execution: Dict[str, Any], runner: Any = None
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


def dump_data_string(
    agent, opt: Optional[Dict[str, Any]] = None
) -> str:
    """Serialize the in-memory dump (upstream dumpDataString)."""
    return json.dumps(
        agent._get_report_builder().to_dict(),
        ensure_ascii=False,
    )


def report_html_string(
    agent, opt: Optional[Dict[str, Any]] = None
) -> str:
    """Render the in-memory dump as a self-contained HTML string."""
    from midscene.core.report_html_template import render_report_html

    return render_report_html(agent._get_report_builder().to_dict(), agent._report_name())


def write_out_action_dumps(
    agent, execution_dump: Optional[Dict[str, Any]] = None
) -> Optional[str]:
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


def add_dump_update_listener(agent, listener: Callable) -> Callable[[], None]:
    """Subscribe to dump updates; returns a remove function."""
    agent._dump_update_listeners.append(listener)

    def remove() -> None:
        agent.remove_dump_update_listener(listener)

    return remove


def remove_dump_update_listener(agent, listener: Callable) -> None:
    try:
        agent._dump_update_listeners.remove(listener)
    except ValueError:
        pass


def clear_dump_update_listeners(agent, ) -> None:
    agent._dump_update_listeners.clear()


def notify_dump_update_listeners(
    agent, execution: Optional[Dict[str, Any]] = None
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
