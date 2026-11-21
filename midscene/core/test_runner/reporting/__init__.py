"""Workflow reporting (upstream packages/core/src/test-runner/reporting)."""

from midscene.core.test_runner.reporting.execution_record import (
    execution_records_to_report_input,
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

__all__ = [
    "MAX_ARRAY_ITEMS",
    "MAX_DEPTH",
    "MAX_OBJECT_KEYS",
    "MAX_SERIALIZED_BYTES",
    "MAX_STRING_LENGTH",
    "TRUNCATED_VALUE",
    "build_test_run_report_plan",
    "collect_test_run_report_metrics",
    "execution_records_to_report_input",
    "sanitize_report_error",
    "sanitize_report_text",
    "sanitize_report_value",
    "sum_test_run_report_metrics",
]
