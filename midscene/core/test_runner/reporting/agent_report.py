"""Agent report to test-run dump (upstream reporting/agent-report.ts)."""

from typing import Any, cast

from midscene.core.test_run_report import IndexedTestRunReportSource, TestRunReportDump
from midscene.core.test_runner.reporting.metrics import (
    collect_test_run_report_metrics,
)
from midscene.core.test_runner.reporting.test_run_report import (
    build_test_run_report_dump,
)
from midscene.core.test_runner.reporting.types import RunReportInput


def build_agent_test_run_report_dump(
    input_value: RunReportInput,
    agent_dump: dict[str, Any],
    source: dict[str, str],
) -> TestRunReportDump:
    executions = agent_dump.get("executions") or []
    sources: list[IndexedTestRunReportSource] = []
    if executions:
        indexed_source: IndexedTestRunReportSource = {
            **cast(IndexedTestRunReportSource, source),
            "executionIds": [
                cast(str, execution["id"])
                for execution in executions
                if execution.get("id")
            ],
        }
        sources.append(indexed_source)
    return build_test_run_report_dump(
        input_value,
        {
            "sources": sources,
            "metrics": collect_test_run_report_metrics(agent_dump),
        },
    )


__all__ = ["build_agent_test_run_report_dump"]
