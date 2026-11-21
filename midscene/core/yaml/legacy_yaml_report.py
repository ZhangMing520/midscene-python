"""Legacy YAML report publication (upstream yaml/legacy-yaml-report.ts).

Report publication is a host projection, not a ScriptPlayer state concern. The
Python host always owns an Agent, so publication goes through the Agent report
hooks (upstream `_writeYamlExecutionReport` / `_createReportSource`); there is
no standalone ReportGenerator port.
"""

import inspect
from typing import Any, Dict, Optional

from loguru import logger

from midscene.core.yaml.report_policy import is_yaml_report_enabled


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def publish_legacy_yaml_report(options: Dict[str, Any]) -> Dict[str, Any]:
    """Write the YAML execution report and attach its source snapshot."""
    agent = options.get("agent")
    run_id = options["runId"]
    record = options["record"]

    if agent is not None:
        writer = getattr(agent, "_write_yaml_execution_report", None)
        report_file: Optional[str] = None
        if callable(writer):
            report_file = await _maybe_await(writer(record))
        if report_file is None:
            report_file = getattr(agent, "report_file", None)
        creator = getattr(agent, "_create_report_source", None)
        source = await _maybe_await(creator(run_id)) if callable(creator) else None
        if source:
            record = {**record, "reportSources": [source]}
        return {"record": record, "reportFile": report_file}

    script = options.get("script") or {}
    if not is_yaml_report_enabled(script):
        return {"record": record}

    # No standalone ReportGenerator port: hosts publish through the Agent.
    logger.debug(
        "legacy YAML report skipped: no agent-backed report generator is configured"
    )
    return {"record": record}


__all__ = ["publish_legacy_yaml_report"]
