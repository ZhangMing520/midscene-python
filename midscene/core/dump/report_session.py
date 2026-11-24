"""Report generation helpers (upstream dump/report-session.ts).

`ReportGenerator` keeps the latest state of every execution and publishes it as
either a single self-contained HTML file (inline mode) or the versioned
`report.json` + `data/` + `screenshots/` directory artifact
(`html-and-external-assets`).
"""

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional, Protocol, TypedDict, cast

from midscene.core.dump.execution_recorder import ExecutionRecorder
from midscene.core.dump.html_utils import (
    DATA_SCREENSHOT_MODE_ATTR,
    generate_agent_report_comment,
    generate_dump_script_tag,
    generate_image_script_tag,
    generate_report_artifact_script_tag,
    generate_test_run_report_script_tag,
    get_base_url_fix_script,
    get_report_tpl,
)
from midscene.core.dump.image_reference import normalize_stored_image_ref
from midscene.core.dump.report_action_dump import ExecutionDump, ReportActionDump
from midscene.core.dump.report_artifact_reader import (
    read_report_artifact_manifest,
)
from midscene.core.dump.report_artifact_store import (
    ReportArtifactStore,
    write_report_artifact_file,
)
from midscene.core.dump.screenshot_store import ReportImageStore
from midscene.core.test_runner.reporting.types import RunReportInput
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
    modelBriefs: list[dict[str, Any]]
    deviceType: str


class IReportGenerator(Protocol):
    """Upstream IReportGenerator surface used by the Python SDK."""

    def on_execution_update(
        self,
        execution: dict[str, Any],
        report_meta: ReportMeta,
        attributes: dict[str, Any] | None = None,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def finalize(self) -> str | None: ...

    def get_report_path(self) -> str | None: ...


class NullReportGenerator:
    """No-op generator used when report generation is disabled."""

    def on_execution_update(
        self,
        execution: dict[str, Any],
        report_meta: ReportMeta,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def finalize(self) -> str | None:
        return None

    def get_report_path(self) -> str | None:
        return None


null_report_generator = NullReportGenerator()


def assert_report_generation_options(opts: dict[str, Any]) -> None:
    """Reject an execution-dump request that has no report to attach to."""
    if opts.get("generateReport") is False and opts.get("persistExecutionDump") is True:
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
    output_format: str | None = None,
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


def _execution_id(execution: Any) -> str | None:
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

    def __init__(self, directory: str, busy: Any | None = None):
        self.directory = directory
        self.busy = busy
        self.snapshot_images: set[str] = set()
        self.recorder = ExecutionRecorder()
        self.id = uuid.uuid4().hex
        self._collected: set[str] = set()
        self._source_path: str | None = None
        self._finalization: asyncio.Future | None = None
        self._uncollected_source: dict[str, Any] | None = None
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
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if self._finalization is not None:
            raise RuntimeError("The report record stream has been finalized.")
        key = self.recorder.record(execution)
        # An update replaces the stored state; snapshots copy it synchronously.
        self._collected.discard(key)

    async def create_source_snapshot(
        self,
        scope_id: str,
        execution_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if self._finalization is not None:
            raise RuntimeError("The report record stream has been finalized.")
        return await self._snapshot(scope_id, execution_ids)

    async def _snapshot(
        self,
        scope_id: str,
        execution_ids: list[str] | None = None,
    ) -> dict[str, Any]:
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

        path = os.path.join(self.directory, f"{self.id}.{uuid.uuid4().hex}.json")
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

        collection: dict[str, Any] = {
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

    async def capture_uncollected(self) -> dict[str, Any] | None:
        if self._finalization is not None:
            await self._finalization
            source = self._uncollected_source
            self._uncollected_source = None
            return source
        return await self._capture_pending()

    async def _capture_pending(self) -> dict[str, Any] | None:
        ids = [
            execution_id
            for execution_id in (
                _execution_id(execution) for execution in self.recorder.executions
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
        self._writers: list[_ReportSourceRecorder] = []
        self._ended = False
        self._completion: list[dict[str, Any]] | None = None
        self._ownership: asyncio.Future | None = None
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
            raise RuntimeError("Start the report session before creating a writer.")
        if self._ended:
            raise RuntimeError("Cannot add a writer to an ended report session.")
        writer = _ReportSourceRecorder(self.directory, is_busy)
        self._writers.append(writer)
        return writer

    async def finish(self) -> list[dict[str, Any]]:
        self._ended = True
        if self._completion is not None:
            return self._completion

        async with self._lock:
            return await self._finish_locked()

    async def _finish_locked(self) -> list[dict[str, Any]]:
        if self._completion is not None:
            return self._completion
        sources: list[dict[str, Any]] = []
        for writer in self._writers:
            source = await writer.capture_uncollected()
            if source:
                sources.append(source)
            if not writer.is_busy():
                await writer.finalize()
            else:
                await writer.flush()
        os.makedirs(self.directory, exist_ok=True)
        os.makedirs(os.path.join(self.directory, "screenshots"), exist_ok=True)
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
            raise RuntimeError("Finish the report session before pruning it.")
        if not self._writers:
            shutil.rmtree(self.directory, ignore_errors=True)
            return
        if any(writer.is_busy() for writer in self._writers):
            return
        shutil.rmtree(os.path.join(self.directory, "data"), ignore_errors=True)
        report_path = os.path.join(self.directory, "report.json")
        if os.path.exists(report_path):
            os.remove(report_path)
        retained = {path for writer in self._writers for path in writer.snapshot_images}
        images_dir = os.path.join(self.directory, "screenshots")
        if os.path.isdir(images_dir):
            for file_name in os.listdir(images_dir):
                if f"./screenshots/{file_name}" not in retained:
                    os.remove(os.path.join(images_dir, file_name))


def current_report_session() -> ReportSession | None:
    return _CURRENT_REPORT_SESSION.get()


class ReportGenerator:
    """Accumulate executions and publish the latest state as a report.

    Inline reports append ``midscene_web_dump``/``midscene-image`` scripts to a
    single HTML file; directory reports split facts into the versioned
    ``report.json`` + ``data/`` + ``screenshots/`` artifact layout. Both modes
    keep the latest state per execution id.
    """

    def __init__(
        self,
        report_path: str | None = None,
        auto_print: bool = True,
        dump: dict[str, Any] | None = None,
        screenshot_mode: str = "inline",
        persist_execution_dump: bool = False,
        reuse_existing_report: bool = False,
    ):
        self.report_path = report_path
        self.auto_print = auto_print
        self.screenshot_mode = (
            screenshot_mode if screenshot_mode in ("inline", "directory") else "inline"
        )
        self.persist_execution_dump = bool(persist_execution_dump)
        self.reuse_existing_report = bool(reuse_existing_report)
        self.report_attributes: dict[str, str] = {}
        self._dump: dict[str, Any] = dump or {}
        existing_executions = self._dump.get("executions")
        self._recorder: ExecutionRecorder | None = (
            ExecutionRecorder(existing_executions)
            if existing_executions is not None
            else None
        )
        self._written = False
        self._dirty = False
        self._finalized = False
        self._printed = False
        self._initialized = False
        self._report_stream_id = uuid.uuid4().hex
        self._last_report_meta: ReportMeta | None = None
        self._source_directory: str | None = None
        self._execution_comment_key_by_object: dict[int, str] = {}
        self._execution_comment_key_index = 0
        self._execution_log_index = 0
        self._execution_log_file_index_by_key: dict[str, int] = {}
        self._artifact_store: ReportArtifactStore | None = None
        self._screenshot_store: ReportImageStore | None = None

        if self.report_path:
            report_dir = os.path.dirname(self.report_path) or "."
            if self.screenshot_mode == "directory":
                self._artifact_store = ReportArtifactStore(
                    report_dir,
                    self._report_stream_id,
                    "agent",
                    self.reuse_existing_report,
                    os.path.basename(self.report_path),
                )
            self._screenshot_store = ReportImageStore(
                mode="inline" if self.screenshot_mode == "inline" else "directory",
                report_path=self.report_path,
                screenshots_dir=(
                    os.path.join(report_dir, "screenshots")
                    if self.screenshot_mode == "directory"
                    or self.persist_execution_dump
                    else None
                ),
                write_inline_image=(
                    self._append_inline_image
                    if self.screenshot_mode == "inline"
                    else None
                ),
                also_write_file_copy=self.persist_execution_dump,
                reuse_existing_report=self.reuse_existing_report,
            )
        if self.reuse_existing_report:
            self._hydrate_state_from_existing_report()

    @classmethod
    def create(cls, report_file_name: str, opts: dict[str, Any]) -> IReportGenerator:
        """Factory mirroring upstream ReportGenerator.create."""
        assert_report_generation_options(opts)
        output_format = opts.get("outputFormat", opts.get("output_format"))
        validate_report_file_name(report_file_name, output_format)
        if opts.get("generateReport") is False:
            return null_report_generator

        report_root_dir = Path(get_midscene_run_dir("report"))
        directory_mode = output_format == "html-and-external-assets"
        if directory_mode:
            report_path = report_root_dir / report_file_name / "index.html"
        else:
            report_path = report_root_dir / ensure_html_file_name(report_file_name)
        return cls(
            report_path=str(report_path),
            auto_print=opts.get("autoPrintReportMsg", True),
            screenshot_mode="directory" if directory_mode else "inline",
            persist_execution_dump=bool(
                opts.get("persistExecutionDump", opts.get("persist_execution_dump"))
            ),
            reuse_existing_report=bool(
                opts.get("reuseExistingReport", opts.get("reuse_existing_report"))
            ),
        )

    def on_execution_update(
        self,
        execution: dict[str, Any],
        report_meta: ReportMeta,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Replace the stored state of an execution (latest state wins)."""
        if self._finalized:
            raise RuntimeError("The report has been finalized.")
        self._merge_report_meta(report_meta)
        self._merge_report_attributes(attributes)
        if self._recorder is None:
            self._recorder = ExecutionRecorder(self._dump.setdefault("executions", []))
        self._recorder.report_meta = report_meta
        self._recorder.record(execution)
        self._dirty = True

    async def flush(self) -> None:
        if self._finalized:
            return
        if self._written and not self._dirty:
            return
        if not self.report_path:
            return
        if self.screenshot_mode == "directory":
            self._flush_directory()
        else:
            self._flush_inline()

    async def finalize(self) -> str | None:
        if not self._finalized:
            await self.flush()
            if self._artifact_store is not None:
                if self._initialized:
                    self._artifact_store.finalize()
            elif self._initialized:
                self._append_agent_report_comment()
                try:
                    from midscene.core.dump.report_dump_compactor import (
                        compact_report_dumps,
                    )

                    compact_report_dumps(cast(str, self.report_path))
                except Exception as error:  # noqa: BLE001 - keep the raw report
                    from loguru import logger

                    logger.warning(
                        f"Failed to compact report {self.report_path}; keeping "
                        f"the uncompressed report: {error}"
                    )
            self._finalized = True
        return self.report_path if self._written else None

    def get_report_path(self) -> str | None:
        return self.report_path

    def enable_source_snapshots(self, scope_id: str | None = None) -> None:
        """Prepare the source-snapshot directory for a report scope."""
        scope_id = scope_id or self._report_stream_id
        if (
            not scope_id
            or scope_id in (".", "..")
            or "/" in scope_id
            or "\\" in scope_id
        ):
            raise ValueError("Invalid report scope ID")
        if self._source_directory is not None:
            return
        self._source_directory = os.path.join(
            get_midscene_run_dir("test-results"), scope_id, "records"
        )

    def _snapshot_meta(self) -> dict[str, Any]:
        return dict(
            self._last_report_meta
            or {
                "sdkVersion": "",
                "groupName": "YAML execution",
                "modelBriefs": [],
            }
        )

    async def create_source_snapshot(
        self,
        scope_id: str,
        execution_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Persist a frozen source snapshot (upstream createSourceSnapshot)."""
        if self._finalized:
            raise RuntimeError("The report has been finalized.")
        if not scope_id or os.path.basename(scope_id) != scope_id:
            raise ValueError("Invalid report scope ID")
        self.enable_source_snapshots(scope_id)

        if self._recorder is None:
            self._recorder = ExecutionRecorder(self._dump.setdefault("executions", []))
        self._recorder.report_meta = self._snapshot_meta()
        captured = self._recorder.capture(execution_ids, self._recorder.report_meta)

        directory = self._source_directory
        assert directory is not None
        os.makedirs(directory, exist_ok=True)
        dump_path = os.path.join(
            directory,
            f"{self._report_stream_id}.{scope_id}.{uuid.uuid4().hex}.json",
        )
        with open(dump_path, "w", encoding="utf-8") as handle:
            handle.write(captured["dump"].serialize())

        return {
            "sourcePath": self.report_path,
            "dumpPath": dump_path,
            "collection": {
                "status": "complete",
                "capturedAt": captured["capturedAt"],
            },
        }

    async def write_runner_report(
        self,
        input: dict[str, Any],
        scope_id: str,
        meta: ReportMeta,
    ) -> str | None:
        """Publish a runner snapshot into this report (upstream writeRunnerReport)."""
        if self._finalized:
            raise RuntimeError("The report has been finalized.")
        self._merge_report_meta(meta)
        if self._recorder is None:
            self._recorder = ExecutionRecorder(self._dump.setdefault("executions", []))
        self._recorder.report_meta = meta
        report_meta = self._last_report_meta
        if report_meta is None:
            report_meta = cast(ReportMeta, dict(meta))
        executions = list(self._recorder.executions)
        agent_dump = ReportActionDump({**report_meta, "executions": executions})
        report_id = (
            self.report_attributes.get("data-report-id")
            or self.report_attributes.get("data-group-id")
            or self._report_stream_id
        )
        from midscene.core.test_runner.reporting.agent_report import (
            build_agent_test_run_report_dump,
        )

        dump = build_agent_test_run_report_dump(
            cast(RunReportInput, input),
            agent_dump.to_json(),
            {
                "reportId": report_id,
                "scopeId": scope_id,
                "sourcePath": self.report_path or "",
            },
        )
        for diagnostic in dump.get("diagnostics") or []:
            from loguru import logger

            logger.warning(diagnostic.get("message"))
        self.enable_source_snapshots(scope_id)
        await self.create_source_snapshot(scope_id)

        if self._artifact_store is not None:
            for execution in executions:
                self._write_execution_to_artifact(execution)
            if not executions:
                # An empty execution group still carries setup/collection
                # diagnostics.
                self._artifact_store.write_execution(
                    "empty",
                    agent_dump.serialize(),
                    self._dump_script_attributes(),
                )
                if not self._initialized:
                    self._initialize_directory_report()
            self._artifact_store.write_runner(json.dumps(dump, ensure_ascii=False))
        else:
            self._flush_inline()
            if not self._initialized:
                self._initialize_inline_report()
            with open(cast(str, self.report_path), "a", encoding="utf-8") as handle:
                handle.write("\n" + generate_test_run_report_script_tag(dump))

        self._written = True
        self._dirty = False
        self._print_report_path()
        return self.report_path

    # -- publication -------------------------------------------------------

    def _initialize_inline_report(self) -> None:
        report_path = cast(str, self.report_path)
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(get_report_tpl(), encoding="utf-8")
        self._initialized = True

    def _initialize_directory_report(self) -> None:
        report_path = cast(str, self.report_path)
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        write_report_artifact_file(
            report_path,
            f"{get_report_tpl()}{get_base_url_fix_script()}\n"
            f"{generate_report_artifact_script_tag('report.json')}",
        )
        self._initialized = True

    def _flush_inline(self) -> None:
        executions = (
            list(self._recorder.executions) if self._recorder is not None else []
        )
        if not executions:
            return
        if not self._initialized:
            self._initialize_inline_report()
        for execution in executions:
            self._write_execution_inline(execution)
            if self.persist_execution_dump:
                self._persist_execution_dump_file(execution)
        self._written = True
        self._dirty = False
        self._print_report_path()

    def _flush_directory(self) -> None:
        executions = (
            list(self._recorder.executions) if self._recorder is not None else []
        )
        if not executions:
            return
        if not self._initialized:
            self._initialize_directory_report()
        assert self._artifact_store is not None
        for execution in executions:
            self._write_execution_to_artifact(execution)
        self._written = True
        self._dirty = False
        self._print_report_path()

    def _append_inline_image(self, image_id: str, data: str) -> None:
        with open(cast(str, self.report_path), "a", encoding="utf-8") as handle:
            handle.write(f"\n{generate_image_script_tag(image_id, data)}")

    def _write_execution_inline(self, execution: Any) -> None:
        dump_execution = self._as_execution_dump(execution)
        self._persist_screenshots(dump_execution)
        reference_refs = self._persist_reference_images(dump_execution)
        single_dump = ReportActionDump(
            {**(self._last_report_meta or {}), "executions": [dump_execution]}
        )
        serialized = single_dump.serialize_with_reference_images(reference_refs)
        with open(cast(str, self.report_path), "a", encoding="utf-8") as handle:
            handle.write(
                "\n"
                + generate_dump_script_tag(serialized, self._dump_script_attributes())
            )

    def _write_execution_to_artifact(self, execution: Any) -> None:
        assert self._artifact_store is not None
        dump_execution = self._as_execution_dump(execution)
        self._persist_screenshots(dump_execution)
        reference_refs = self._persist_reference_images(dump_execution)
        single_dump = ReportActionDump(
            {**(self._last_report_meta or {}), "executions": [dump_execution]}
        )
        serialized = single_dump.serialize_with_reference_images(reference_refs)
        self._artifact_store.write_execution(
            self._execution_comment_key(execution),
            serialized,
            self._dump_script_attributes(),
        )

    def _persist_screenshots(self, dump_execution: ExecutionDump) -> None:
        if self._screenshot_store is None:
            return
        for screenshot in dump_execution.collect_screenshots():
            self._screenshot_store.persist(screenshot)

    def _persist_reference_images(
        self, dump_execution: ExecutionDump
    ) -> dict[str, Any]:
        refs: dict[str, Any] = {}
        if self._screenshot_store is None:
            return refs
        for image_url in dump_execution.get_reference_image_urls():
            refs[image_url] = self._screenshot_store.persist_reference_image(image_url)
        return refs

    def _dump_script_attributes(self) -> dict[str, str]:
        return {
            "data-group-id": self._report_stream_id,
            DATA_SCREENSHOT_MODE_ATTR: self.screenshot_mode,
            **self.report_attributes,
            "data-report-kind": "agent",
        }

    def _append_agent_report_comment(self) -> None:
        if self._recorder is None or not self._recorder.executions:
            return
        report_dump = ReportActionDump(
            {
                **(self._last_report_meta or self._snapshot_meta()),
                "executions": self._recorder.executions,
            }
        )
        with open(cast(str, self.report_path), "a", encoding="utf-8") as handle:
            handle.write("\n" + generate_agent_report_comment(report_dump.to_json()))

    def _execution_comment_key(self, execution: Any) -> str:
        execution_id = _execution_id(execution)
        if execution_id:
            return f"id:{execution_id}"
        object_key = id(execution)
        existing = self._execution_comment_key_by_object.get(object_key)
        if existing is not None:
            return existing
        key = f"no-id:{self._execution_comment_key_index}"
        self._execution_comment_key_index += 1
        self._execution_comment_key_by_object[object_key] = key
        return key

    def _execution_log_key(self, execution: Any) -> str:
        execution_id = _execution_id(execution)
        if not execution_id:
            raise ValueError(
                "ReportGenerator: execution.id is required for persisting "
                "execution dumps"
            )
        return f"id:{execution_id}"

    def _execution_dump_directory(self) -> str:
        report_dir = os.path.dirname(cast(str, self.report_path)) or "."
        if self.screenshot_mode == "inline":
            return os.path.join(
                report_dir,
                ".execution-dumps",
                os.path.basename(cast(str, self.report_path)),
            )
        return report_dir

    def _persist_execution_dump_file(self, execution: Any) -> None:
        directory = self._execution_dump_directory()
        os.makedirs(directory, exist_ok=True)
        key = self._execution_log_key(execution)
        file_index = self._execution_log_file_index_by_key.get(key)
        if file_index is None:
            self._execution_log_index += 1
            file_index = self._execution_log_index
            self._execution_log_file_index_by_key[key] = file_index
        dump_execution = self._as_execution_dump(execution)
        single_dump = ReportActionDump(
            {**(self._last_report_meta or {}), "executions": [dump_execution]}
        )
        reference_refs = self._persist_reference_images(dump_execution)
        serialized = single_dump.serialize_with_reference_images(reference_refs, 2)
        if self.screenshot_mode == "inline":
            serialized = json.dumps(
                self._rewrite_inline_dump_refs_to_files(json.loads(serialized)),
                ensure_ascii=False,
                indent=2,
            )
        write_report_artifact_file(
            os.path.join(directory, f"{file_index}.execution.json"),
            serialized,
        )

    def _rewrite_inline_dump_refs_to_files(self, value: Any) -> Any:
        ref = normalize_stored_image_ref(value)
        if ref is not None:
            if ref.get("storage") != "inline" or self._screenshot_store is None:
                return value
            try:
                path = self._screenshot_store.get_file_path(ref["id"])
            except ValueError:
                return value
            return {
                **ref,
                "storage": "file",
                "path": f"../../{path[2:] if path.startswith('./') else path}",
            }
        if isinstance(value, dict):
            return {
                key: self._rewrite_inline_dump_refs_to_files(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._rewrite_inline_dump_refs_to_files(item) for item in value]
        return value

    def _hydrate_state_from_existing_report(self) -> None:
        if not self.report_path or not os.path.exists(self.report_path):
            return
        if (
            self._artifact_store is not None
            and read_report_artifact_manifest(self.report_path) is None
        ):
            raise ValueError(
                "Cannot reuse an incompatible directory report. Choose a new "
                "reportFileName or regenerate the report."
            )
        self._initialized = True
        if not self.persist_execution_dump:
            return
        directory = self._execution_dump_directory()
        if not os.path.isdir(directory):
            return
        indices = [
            int(match.group(1))
            for match in (
                re.match(r"^(\d+)\.execution\.json$", name)
                for name in os.listdir(directory)
            )
            if match
        ]
        if indices:
            self._execution_log_index = max(indices)

    @staticmethod
    def _as_execution_dump(execution: Any) -> ExecutionDump:
        if isinstance(execution, ExecutionDump):
            return execution
        return ExecutionDump.from_json(execution)

    def _merge_report_meta(self, report_meta: ReportMeta) -> None:
        self._last_report_meta = cast(ReportMeta, dict(report_meta))
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

    def _merge_report_attributes(self, attributes: dict[str, Any] | None) -> None:
        if not attributes:
            return
        for key, value in attributes.items():
            if value is None:
                continue
            self.report_attributes[key] = str(value)

    def _print_report_path(self) -> None:
        if not self.auto_print or self._printed or not self.report_path:
            return
        self._printed = True
        if os.environ.get("MIDSCENE_REPORT_QUIET"):
            return
        from loguru import logger

        if self.screenshot_mode == "directory":
            logger.info(
                "Midscene - report file updated: npx serve "
                f"{os.path.dirname(self.report_path)}"
            )
        else:
            logger.info(f"Midscene - report file updated: {self.report_path}")
