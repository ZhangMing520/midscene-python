"""Report CLI helpers: read / split / merge (upstream core/src/report-cli.ts).

The implementation lives in `midscene.core.dump.report_dump_compactor` and
`midscene.core.dump.test_report_images`; this module re-exports the original
names so existing imports keep working.
"""

from midscene.core.dump.report_dump_compactor import (
    _DUMP_HEADER_KEYS,
    _REPORT_DUMP_PATTERN,
    _dedupe_executions,
    collect_report_executions,
    merge_report_files,
    read_report_dump,
    resolve_report_html_path,
)
from midscene.core.dump.test_report_images import split_report_file

__all__ = [
    "_DUMP_HEADER_KEYS",
    "_REPORT_DUMP_PATTERN",
    "_dedupe_executions",
    "collect_report_executions",
    "merge_report_files",
    "read_report_dump",
    "resolve_report_html_path",
    "split_report_file",
]
