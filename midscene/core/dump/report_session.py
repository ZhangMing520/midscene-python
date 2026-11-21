"""Report generation helpers (upstream dump/report-session.ts).

The Python SDK renders a single self-contained HTML report, so the streaming
writer from upstream is reduced to: keep the latest state of every execution
and flush it through `write_report_html`. Directory (`html-and-external-assets`)
reports are not produced here.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TypedDict

from midscene.core.dump.execution_recorder import ExecutionRecorder
from midscene.core.report import write_report_html
from midscene.shared.env import get_midscene_run_dir

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

MAX_REPORT_FILENAME_BYTES = 255


class ReportMeta(TypedDict, total=False):
    sdkVersion: str
    groupName: str
    groupDescription: str
    modelBriefs: List[Dict[str, Any]]
    deviceType: str


class IReportGenerator(Protocol):
    """Upstream IReportGenerator surface used by the Python SDK."""

    def on_execution_update(
        self,
        execution: Dict[str, Any],
        report_meta: ReportMeta,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def finalize(self) -> Optional[str]: ...

    def get_report_path(self) -> Optional[str]: ...


class NullReportGenerator:
    """No-op generator used when report generation is disabled."""

    def on_execution_update(self, execution, report_meta, attributes=None) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def finalize(self) -> Optional[str]:
        return None

    def get_report_path(self) -> Optional[str]:
        return None


null_report_generator = NullReportGenerator()


def assert_report_generation_options(opts: Dict[str, Any]) -> None:
    """Reject an execution-dump request that has no report to attach to."""
    if (
        opts.get("generateReport") is False
        and opts.get("persistExecutionDump") is True
    ):
        raise ValueError(
            "persistExecutionDump cannot be true when generateReport is false"
        )


def ensure_html_file_name(report_file_name: str) -> str:
    return (
        report_file_name
        if report_file_name.endswith(".html")
        else f"{report_file_name}.html"
    )


def validate_report_file_name(
    report_file_name: str,
    output_format: Optional[str] = None,
) -> None:
    """Validate a user-supplied report name (upstream validateReportFileName)."""
    if not report_file_name or not report_file_name.strip():
        raise ValueError("reportFileName must be a non-empty string")

    if "/" in report_file_name or "\\" in report_file_name:
        raise ValueError(
            "reportFileName must not contain path separators (`/` or `\\\\`)"
        )

    if any(char in report_file_name for char in ':*?"<>|'):
        raise ValueError(
            'reportFileName contains illegal filename characters: : * ? " < > |'
        )

    filename_component = (
        report_file_name
        if output_format == "html-and-external-assets"
        else ensure_html_file_name(report_file_name)
    )
    filename_bytes = len(filename_component.encode("utf-8"))
    if filename_bytes > MAX_REPORT_FILENAME_BYTES:
        raise ValueError(
            f"reportFileName produces a filename component of {filename_bytes} "
            f"UTF-8 bytes; maximum is {MAX_REPORT_FILENAME_BYTES}"
        )


class ReportGenerator:
    """Accumulate executions and render the latest state to one HTML report."""

    def __init__(
        self,
        report_path: Optional[str] = None,
        auto_print: bool = True,
        dump: Optional[Dict[str, Any]] = None,
    ):
        self.report_path = report_path
        self.auto_print = auto_print
        self.report_attributes: Dict[str, str] = {}
        self._dump: Dict[str, Any] = dump or {}
        existing_executions = self._dump.get("executions")
        self._recorder: Optional[ExecutionRecorder] = (
            ExecutionRecorder(existing_executions)
            if existing_executions is not None
            else None
        )
        self._written = False
        self._finalized = False
        self._printed = False

    @classmethod
    def create(cls, report_file_name: str, opts: Dict[str, Any]) -> IReportGenerator:
        """Factory mirroring upstream ReportGenerator.create."""
        assert_report_generation_options(opts)
        output_format = opts.get("outputFormat")
        validate_report_file_name(report_file_name, output_format)
        if opts.get("generateReport") is False:
            return null_report_generator

        report_root_dir = Path(get_midscene_run_dir("report"))
        if output_format == "html-and-external-assets":
            # The Python SDK only emits the single-file report format.
            report_path = report_root_dir / report_file_name / "index.html"
        else:
            report_path = report_root_dir / ensure_html_file_name(report_file_name)
        return cls(
            report_path=str(report_path),
            auto_print=opts.get("autoPrintReportMsg", True),
        )

    def on_execution_update(
        self,
        execution: Dict[str, Any],
        report_meta: ReportMeta,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace the stored state of an execution (latest state wins)."""
        if self._finalized:
            raise RuntimeError("The report has been finalized.")
        self._merge_report_meta(report_meta)
        self._merge_report_attributes(attributes)
        if self._recorder is None:
            self._recorder = ExecutionRecorder(
                self._dump.setdefault("executions", [])
            )
        self._recorder.record(execution)
        self._written = False

    async def flush(self) -> None:
        if self._written or not self._dump or not self.report_path:
            return
        path = Path(self.report_path)
        html_path = write_report_html(
            self._dump,
            path.stem,
            str(path.parent),
        )
        if html_path:
            self._written = True
            self._print_report_path(html_path)

    async def finalize(self) -> Optional[str]:
        if not self._finalized:
            await self.flush()
            self._finalized = True
        return self.report_path if self._written else None

    def get_report_path(self) -> Optional[str]:
        return self.report_path

    def _merge_report_meta(self, report_meta: ReportMeta) -> None:
        if "sdkVersion" not in self._dump and report_meta.get("sdkVersion"):
            self._dump["sdkVersion"] = report_meta["sdkVersion"]
        if report_meta.get("groupName"):
            self._dump["groupName"] = report_meta["groupName"]
        if report_meta.get("groupDescription") is not None:
            self._dump["groupDescription"] = report_meta["groupDescription"]
        if report_meta.get("modelBriefs") is not None:
            self._dump["modelBriefs"] = report_meta["modelBriefs"]
        if report_meta.get("deviceType"):
            self._dump["deviceType"] = report_meta["deviceType"]

    def _merge_report_attributes(
        self, attributes: Optional[Dict[str, Any]]
    ) -> None:
        if not attributes:
            return
        for key, value in attributes.items():
            if value is None:
                continue
            self.report_attributes[key] = str(value)

    def _print_report_path(self, html_path: str) -> None:
        if not self.auto_print or self._printed:
            return
        self._printed = True
        if os.environ.get("MIDSCENE_REPORT_QUIET"):
            return
        from loguru import logger

        logger.info(f"Midscene - report file updated: {html_path}")
