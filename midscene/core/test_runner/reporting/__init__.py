"""Workflow reporting (upstream packages/core/src/test-runner/reporting)."""

from midscene.core.test_runner.reporting.agent_report import (
    build_agent_test_run_report_dump,
)
from midscene.core.test_runner.reporting.execution_record import (
    execution_records_to_report_input,
)
from midscene.core.test_runner.reporting.merge_report import (
    MergeTestRunReportSource,
    merge_test_run_report_dumps,
)
from midscene.core.test_runner.reporting.metrics import (
    collect_test_run_report_metrics,
    sum_test_run_report_metrics,
)
from midscene.core.test_runner.reporting.sanitize import (
    MAX_ARRAY_ITEMS,
    MAX_DEPTH,
    MAX_OBJECT_KEYS,
    MAX_SERIALIZED_BYTES,
    MAX_STRING_LENGTH,
    TRUNCATED_VALUE,
    sanitize_report_error,
    sanitize_report_text,
    sanitize_report_value,
)
from midscene.core.test_runner.reporting.test_plan import build_test_run_report_plan
from midscene.core.test_runner.reporting.test_run_report import (
    build_test_run_report_dump,
    collect_test_run_report_sources,
)

__all__ = [
    "MAX_ARRAY_ITEMS",
    "MAX_DEPTH",
    "MAX_OBJECT_KEYS",
    "MAX_SERIALIZED_BYTES",
    "MAX_STRING_LENGTH",
    "MergeTestRunReportSource",
    "TRUNCATED_VALUE",
    "build_agent_test_run_report_dump",
    "build_test_run_report_dump",
    "build_test_run_report_plan",
    "collect_test_run_report_metrics",
    "collect_test_run_report_sources",
    "execution_records_to_report_input",
    "merge_test_run_report_dumps",
    "sanitize_report_error",
    "sanitize_report_text",
    "sanitize_report_value",
    "sum_test_run_report_metrics",
]
