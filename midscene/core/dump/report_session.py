"""Report generation helpers (upstream dump/report-session.ts).

The Python SDK renders a single self-contained HTML report, so the streaming
writer from upstream is reduced to: keep the latest state of every execution
and flush it through `write_report_html`. Directory (`html-and-external-assets`)
reports are not produced here.
"""

import asyncio
import json
import os
import shutil
import time
import uuid
from contextvars import ContextVar
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
    "ReportSession",
    "assert_report_generation_options",
    "current_report_session",
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


_CURRENT_REPORT_SESSION: ContextVar[Optional["ReportSession"]] = ContextVar(
    "midscene_report_session", default=None
)


def _execution_id(execution: Any) -> Optional[str]:
    if isinstance(execution, dict):
        return execution.get("id")
    return getattr(execution, "id", None)


def _json_default(value: Any) -> Any:
    for method_name in ("toSerializable", "to_serializable", "serialize"):
        method = getattr(value, method_name, None)
        if callable(method):
            return method()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


class _ReportSourceRecorder:
    """Structured Agent records plus immutable Step cutoffs (upstream writer)."""

    def __init__(self, directory: str, busy: Optional[Any] = None):
        self.directory = directory
        self.busy = busy
        self.snapshot_images: set = set()
        self.recorder = ExecutionRecorder()
        self.id = uuid.uuid4().hex
        self._collected = set()
        self._source_path: Optional[str] = None
        self._finalization: Optional[asyncio.Future] = None
        self._uncollected_source: Optional[Dict[str, Any]] = None
        self._queue: asyncio.Lock = asyncio.Lock()

    def get_report_path(self) -> None:
        return None

    def enable_source_snapshots(self) -> None:
        return None

    def is_busy(self) -> bool:
        if self.busy is None:
            return False
        try:
            return bool(self.busy())
        except Exception:  # noqa: BLE001 - a broken predicate must not fail reports
            return False

    def on_execution_update(
        self,
        execution: Any,
        report_meta: ReportMeta,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._finalization is not None:
            raise RuntimeError("The report record stream has been finalized.")
        key = self.recorder.record(execution)
        # An update replaces the stored state; snapshots copy it synchronously.
        self._collected.discard(key)

    async def create_source_snapshot(
        self,
        scope_id: str,
        execution_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if self._finalization is not None:
            raise RuntimeError("The report record stream has been finalized.")
        return await self._snapshot(scope_id, execution_ids)

    async def _snapshot(
        self,
        scope_id: str,
        execution_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(scope_id, str) or not scope_id.strip():
            raise ValueError("Invalid report scope ID")

        busy_at_cutoff = self.is_busy()
        if execution_ids is None:
            captured = list(self.recorder.executions)
        else:
            wanted = set(execution_ids)
            captured = [
                execution
                for execution in self.recorder.executions
                if _execution_id(execution) in wanted
            ]

        path = os.path.join(
            self.directory, f"{self.id}.{uuid.uuid4().hex}.json"
        )
        payload = {"executions": captured}
        async with self._queue:
            os.makedirs(self.directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, default=_json_default)
            if self._source_path is None:
                self._source_path = path
            for execution in captured:
                execution_id = _execution_id(execution)
                if execution_id:
                    self._collected.add(execution_id)

        collection: Dict[str, Any] = {
            "status": "partial" if busy_at_cutoff else "complete",
            "capturedAt": int(time.time() * 1000),
        }
        if busy_at_cutoff:
            collection["reason"] = (
                "An Agent operation was still running at the snapshot cutoff."
            )
        return {
            "sourcePath": self._source_path,
            "dumpPath": path,
            "collection": collection,
        }

    async def capture_uncollected(self) -> Optional[Dict[str, Any]]:
        if self._finalization is not None:
            await self._finalization
            source = self._uncollected_source
            self._uncollected_source = None
            return source
        return await self._capture_pending()

    async def _capture_pending(self) -> Optional[Dict[str, Any]]:
        ids = [
            execution_id
            for execution_id in (
                _execution_id(execution)
                for execution in self.recorder.executions
            )
            if execution_id and execution_id not in self._collected
        ]
        if not ids:
            return None
        return await self._snapshot(self.id, ids)

    async def flush(self) -> None:
        async with self._queue:
            return None

    async def finalize(self) -> None:
        if self._finalization is None:
            self._finalization = asyncio.ensure_future(self._finalize_impl())
        await self._finalization

    async def _finalize_impl(self) -> None:
        await self.flush()
        self._uncollected_source = await self._capture_pending()
        self.recorder.clear()
        self._collected.clear()
        self.busy = None
        return None


class ReportSession:
    """The execution host owns the records; Agents do not publish pages."""

    def __init__(self, directory: str):
        if not os.path.isabs(directory):
            raise ValueError("Report session directory must be absolute.")
        self.directory = directory
        self._writers: List[_ReportSourceRecorder] = []
        self._ended = False
        self._completion: Optional[List[Dict[str, Any]]] = None
        self._ownership: Optional[asyncio.Future] = None
        self._lock = asyncio.Lock()

    async def run(self, callback: Any) -> Any:
        if self._ended:
            raise RuntimeError("The report session has ended.")
        if self._ownership is None:
            self._ownership = asyncio.ensure_future(self._claim_directory())
        await self._ownership
        token = _CURRENT_REPORT_SESSION.set(self)
        try:
            result = callback()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        finally:
            _CURRENT_REPORT_SESSION.reset(token)

    async def _claim_directory(self) -> None:
        os.makedirs(os.path.dirname(self.directory), exist_ok=True)
        os.makedirs(self.directory, exist_ok=True)

    def create_recorder(self, is_busy: Any) -> _ReportSourceRecorder:
        if self._ownership is None:
            raise RuntimeError(
                "Start the report session before creating a writer."
            )
        if self._ended:
            raise RuntimeError(
                "Cannot add a writer to an ended report session."
            )
        writer = _ReportSourceRecorder(self.directory, is_busy)
        self._writers.append(writer)
        return writer

    async def finish(self) -> List[Dict[str, Any]]:
        self._ended = True
        if self._completion is not None:
            return self._completion

        async with self._lock:
            if self._completion is not None:
                return self._completion
            sources: List[Dict[str, Any]] = []
            for writer in self._writers:
                source = await writer.capture_uncollected()
                if source:
                    sources.append(source)
                if not writer.is_busy():
                    await writer.finalize()
                else:
                    await writer.flush()
            os.makedirs(self.directory, exist_ok=True)
            os.makedirs(
                os.path.join(self.directory, "screenshots"), exist_ok=True
            )
            with open(
                os.path.join(self.directory, "report.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"status": "complete"}, handle)
            self._completion = sources
            return sources

    async def prune(self) -> None:
        if self._completion is None:
            raise RuntimeError(
                "Finish the report session before pruning it."
            )
        if not self._writers:
            shutil.rmtree(self.directory, ignore_errors=True)
            return
        if any(writer.is_busy() for writer in self._writers):
            return
        shutil.rmtree(
            os.path.join(self.directory, "data"), ignore_errors=True
        )
        report_path = os.path.join(self.directory, "report.json")
        if os.path.exists(report_path):
            os.remove(report_path)
        retained = {
            path
            for writer in self._writers
            for path in writer.snapshot_images
        }
        images_dir = os.path.join(self.directory, "screenshots")
        if os.path.isdir(images_dir):
            for file_name in os.listdir(images_dir):
                if f"./screenshots/{file_name}" not in retained:
                    os.remove(os.path.join(images_dir, file_name))


def current_report_session() -> Optional[ReportSession]:
    return _CURRENT_REPORT_SESSION.get()


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
