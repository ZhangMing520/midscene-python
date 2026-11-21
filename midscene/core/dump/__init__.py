"""Execution dump structures aligned with the upstream report format.

The implementation lives in `report_action_dump` (upstream
dump/report-action-dump.ts); this package re-exports the original names so
existing imports keep working.
"""

from midscene.core.dump.report_action_dump import (
    ExecutionDumpBuilder,
    build_execution_task,
    build_service_dump,
    get_report_file_name,
    new_log_id,
    new_task_id,
)

__all__ = [
    "build_service_dump",
    "build_execution_task",
    "ExecutionDumpBuilder",
    "get_report_file_name",
    "new_task_id",
]
