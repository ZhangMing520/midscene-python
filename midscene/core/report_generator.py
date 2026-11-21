"""Report generation helpers (upstream core/src/report-generator.ts).

The implementation lives in `midscene.core.dump.report_session` (upstream
dump/report-session.ts); this module re-exports the original names so existing
imports keep working.
"""

from midscene.core.dump.report_session import (
    MAX_REPORT_FILENAME_BYTES,
    IReportGenerator,
    NullReportGenerator,
    ReportGenerator,
    ReportMeta,
    assert_report_generation_options,
    ensure_html_file_name,
    null_report_generator,
    validate_report_file_name,
)

__all__ = [
    "MAX_REPORT_FILENAME_BYTES",
    "ReportMeta",
    "IReportGenerator",
    "NullReportGenerator",
    "null_report_generator",
    "assert_report_generation_options",
    "ensure_html_file_name",
    "validate_report_file_name",
    "ReportGenerator",
]
