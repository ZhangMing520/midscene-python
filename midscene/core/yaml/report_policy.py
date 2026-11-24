"""YAML report policy (upstream yaml/report-policy.ts)."""

from typing import Any

from loguru import logger


def is_yaml_report_enabled(script: dict[str, Any]) -> bool:
    """Whether a YAML script should publish a report."""
    web_target = (
        script.get("page")
        or script.get("browser")
        or script.get("web")
        or script.get("target")
    )
    agent = script.get("agent") or {}
    if agent.get("generateReport") is not None:
        return agent["generateReport"] is not False
    if isinstance(web_target, dict) and web_target.get("generateReport") is not None:
        return web_target["generateReport"] is not False
    return True


def _execution_count(agent: Any) -> int:
    """Number of executions already recorded on the agent's report."""
    builder = getattr(agent, "_report_builder", None)
    if builder is None:
        return 0
    return len(builder.dump.get("executions") or [])


def _has_failed_execution_since(agent: Any, execution_count_before: int) -> bool:
    builder = getattr(agent, "_report_builder", None)
    if builder is None:
        return False
    executions = builder.dump.get("executions") or []
    for execution in executions[execution_count_before:]:
        for task in execution.get("tasks") or []:
            if task.get("status") == "failed":
                return True
    return False


async def _record_yaml_task_error(
    agent: Any,
    task_name: str,
    flow_index: int,
    error: BaseException,
    execution_count_before: int,
) -> None:
    """Record a YAML task failure unless the failing step already did."""
    recorder = getattr(agent, "record_error_to_report", None)
    if recorder is None or _has_failed_execution_since(agent, execution_count_before):
        return
    try:
        await recorder(
            f"YAML task failed - {task_name}",
            {
                "error": error,
                "content": (
                    f'Step {flow_index} failed while running YAML task "{task_name}".'
                ),
            },
        )
    except Exception as record_error:
        logger.debug(f"failed to record yaml error to report: {record_error}")
