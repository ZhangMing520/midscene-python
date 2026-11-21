"""Workflow document runtime (upstream engine/document-runtime.ts)."""

import asyncio
import datetime
import inspect
import uuid
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from midscene.core.test_runner.engine.execute_step import execute_step
from midscene.core.test_runner.engine.execution_failure import (
    WorkflowAggregateError,
    WorkflowExecutionFailure,
    as_execution_error,
)
from midscene.core.test_runner.engine.resource_operations import (
    ResourceCleanupDeferredError,
    cleanup_scope_resources,
    create_resource_scope,
    get_pending_scope_operations,
    get_resource_cleanup_snapshot,
    recover_cancelled_scope_resources,
    set_resource_operation_identity,
)
from midscene.core.test_runner.engine.result_metadata import phase_result
from midscene.core.test_runner.engine.scope_teardown import report_paths_from_teardown
from midscene.core.test_runner.engine.setup_timeout import run_setup_with_timeout
from midscene.core.test_runner.errors import (
    NodeScopeTeardownError,
    WorkflowLifecycleError,
)
from midscene.core.test_runner.parser.types import CollectedWorkflowDocument
from midscene.core.test_runner.reporting.test_plan import build_test_run_report_plan


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _call(callback: Optional[Callable[..., Any]], *args: Any) -> None:
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _teardown_timeout(options: Dict[str, Any]) -> Optional[float]:
    value = options.get("teardownTimeoutMs")
    if value is None:
        return None
    return value() if callable(value) else value


def _document_setup_parts(definition: Any) -> Optional[Dict[str, Any]]:
    if definition is None:
        return None
    if isinstance(definition, dict):
        return {
            "name": definition.get("name", "document-setup"),
            "setup": definition.get("setup"),
            "onDocumentResult": definition.get("onDocumentResult"),
        }
    return {
        "name": getattr(definition, "name", "document-setup"),
        "setup": getattr(definition, "setup", None),
        "onDocumentResult": getattr(definition, "onDocumentResult", None),
    }


class DocumentRuntime:
    """One document attempt: setup, beforeAll, then case execution."""

    def __init__(
        self,
        document: CollectedWorkflowDocument,
        options: Dict[str, Any],
    ) -> None:
        self._document = document
        self._options = options
        create_run_id = options.get("createDocumentRunId")
        self._document_run_id = (
            create_run_id() if create_run_id else uuid.uuid4().hex
        )
        self._project = options.get("project") or {
            "projectId": document.get("projectId"),
            "name": document.get("projectId"),
            "retry": 0,
        }
        self._plan = options.get("plan") or build_test_run_report_plan(
            document,
            {
                "defaultTimeoutMs": options.get("defaultTimeoutMs"),
                "retry": {
                    "scope": "case",
                    "count": self._project.get("retry", 0),
                },
            },
        )
        self._started_at = _now()
        self._before_all: List[Dict[str, Any]] = []
        self._after_all: List[Dict[str, Any]] = []
        self._nodes = {
            "beforeAll": [
                options["resolveNode"](step.get("node"))
                for step in document["lifecycle"]["beforeAll"]
            ],
            "afterAll": [
                options["resolveNode"](step.get("node"))
                for step in document["lifecycle"]["afterAll"]
            ],
        }
        self._context = options.get("projectContext")
        self._resource_scope = create_resource_scope(options.get("signal"))
        self._signal = self._resource_scope.signal
        set_resource_operation_identity(
            self._signal, {"scopeId": self._document_run_id}
        )
        self._node_teardown_stack: List[Dict[str, Any]] = []
        self._accepting_node_teardowns = True
        self._started = False
        self._finish_task: Optional["asyncio.Future[Any]"] = None
        self._report_paths: List[str] = []
        self._report_sources: List[Dict[str, Any]] = []
        self._captured_sources: Dict[str, Dict[str, Any]] = {}
        self._execution_errors: List[Any] = []
        self._host_errors: List[Dict[str, Any]] = []
        self._accepting_setup_teardowns = False
        self._document_setup = _document_setup_parts(
            options.get("documentSetup")
        )

    @property
    def signal(self) -> Any:
        return self._signal

    @property
    def context(self) -> Any:
        return self._context

    @property
    def document_run_id(self) -> str:
        return self._document_run_id

    @property
    def plan(self) -> Any:
        return self._plan

    @property
    def can_run_cases(self) -> bool:
        from midscene.core.test_runner.engine._abort import is_aborted

        return (
            self._started
            and not self._execution_errors
            and not self._host_errors
            and not is_aborted(self._signal)
            and not any(
                step.get("status") != "success" for step in self._before_all
            )
        )

    def _create_result(
        self, teardown_errors: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        teardown_errors = teardown_errors or []
        document = self._document
        ended_at = _now()
        cleanup = get_resource_cleanup_snapshot(self._signal)
        pending = get_pending_scope_operations(self._signal)
        phase_results = {
            "beforeAll": phase_result(
                len(document["lifecycle"]["beforeAll"]), self._before_all
            ),
            "afterAll": phase_result(
                len(document["lifecycle"]["afterAll"]), self._after_all
            ),
        }
        has_failed_phase = any(
            phase.get("status") == "failed" for phase in phase_results.values()
        )
        has_not_run_phase = any(
            phase.get("status") == "not-run" for phase in phase_results.values()
        )
        from midscene.core.test_runner.engine._abort import is_aborted

        not_run = (
            has_not_run_phase
            or any(host.get("phase") == "setup" for host in self._host_errors)
            or (
                is_aborted(self._signal)
                and not self._before_all
                and not self._after_all
            )
        )
        failed = (
            bool(self._execution_errors)
            or bool(self._host_errors)
            or any(step.get("status") != "success" for step in self._before_all)
            or any(step.get("status") != "success" for step in self._after_all)
            or cleanup.get("status") in ("pending", "failed")
            or bool(pending)
            or bool(teardown_errors)
        )
        execution_errors = [
            as_execution_error(error)
            for error in self._execution_errors
            if not any(host.get("error") is error for host in self._host_errors)
        ]
        result: Dict[str, Any] = {
            "plan": self._plan,
            "documentId": document["documentId"],
            "documentRunId": self._document_run_id,
            "projectId": document.get("projectId"),
            "projectName": self._project.get("name"),
            "sourcePath": document.get("sourcePath"),
            "status": "failed" if failed else "success",
            "executionStatus": (
                "failed"
                if has_failed_phase
                else "not-run"
                if not_run
                else "success"
            ),
            "phases": phase_results,
            "cleanup": cleanup,
            "startedAt": _iso(self._started_at),
            "endedAt": _iso(ended_at),
            "durationMs": max(
                0.0, (ended_at - self._started_at).total_seconds() * 1000
            ),
            "beforeAll": list(self._before_all),
            "afterAll": list(self._after_all),
        }
        if self._options.get("documentAttemptIndex") is not None:
            result["attemptIndex"] = self._options["documentAttemptIndex"]
        if pending:
            result["pendingOperations"] = pending
        if execution_errors:
            result["executionErrors"] = execution_errors
        if self._host_errors:
            result["hostErrors"] = list(self._host_errors)
        if teardown_errors:
            result["teardownErrors"] = list(teardown_errors)
        if self._report_paths:
            result["reportPaths"] = list(self._report_paths)
        if self._captured_sources or self._report_sources:
            result["reportSources"] = [
                *self._captured_sources.values(),
                *self._report_sources,
            ]
        return result

    async def _run_phase(
        self,
        phase: str,
        results: List[Dict[str, Any]],
        execution_signal: Any = None,
    ) -> None:
        signal = self._signal if execution_signal is None else execution_signal
        steps = self._document["lifecycle"][phase]
        for step_index, step in enumerate(steps):
            wait_for_previous_ms = (
                await recover_cancelled_scope_resources(signal)
                if step_index > 0
                else 0
            )
            document_context = {
                "documentId": self._document["documentId"],
                "documentRunId": self._document_run_id,
                "projectId": self._document.get("projectId"),
                "projectName": self._project.get("name"),
                "sourcePath": self._document.get("sourcePath"),
                "phase": phase,
                "stepIndex": step_index,
            }
            step_info = {
                "scope": "document",
                "node": step.get("node"),
                "stepCount": len(steps),
                "document": document_context,
            }
            await _call(self._options.get("onStepStart"), step_info)
            result = await execute_step(
                step,
                self._nodes[phase][step_index],
                {"scope": "document", "document": document_context},
                self._context,
                {
                    "signal": signal,
                    "defaultTimeoutMs": self._options.get("defaultTimeoutMs"),
                    "onTeardown": self._on_node_teardown,
                },
            )
            if wait_for_previous_ms > 0:
                result["waitForPreviousOperationMs"] = wait_for_previous_ms
            results.append(result)
            for source in (result.get("report") or {}).get("sources") or []:
                caption = (
                    f"{source.get('sourcePath')}\u0000{source.get('dumpPath') or ''}"
                )
                self._captured_sources[caption] = source
            await _call(self._options.get("onStepResult"), step_info, result)
            if result.get("status") != "success" and not result.get(
                "continuedAfterError"
            ):
                break

    def _on_node_teardown(self, node: str, teardown: Any) -> None:
        if not self._accepting_node_teardowns:
            raise WorkflowLifecycleError(
                "Node teardown can only be registered while a workflow document is running.",
                {
                    "documentId": self._document["documentId"],
                    "documentRunId": self._document_run_id,
                    "node": node,
                },
            )
        if not callable(teardown):
            raise WorkflowLifecycleError(
                "Node onTeardown() requires a teardown function.",
                {
                    "documentId": self._document["documentId"],
                    "documentRunId": self._document_run_id,
                    "node": node,
                },
            )
        self._node_teardown_stack.append(
            {
                "registrationIndex": len(self._node_teardown_stack),
                "node": node,
                "teardown": teardown,
            }
        )

    async def start(self) -> Dict[str, Any]:
        if self._started:
            raise WorkflowLifecycleError(
                "Workflow document runtime has already started.",
                {
                    "documentId": self._document["documentId"],
                    "documentRunId": self._document_run_id,
                },
            )
        self._started = True
        if not self._signal.aborted and self._document_setup is not None:
            self._accepting_setup_teardowns = True
            setup_fn = self._document_setup["setup"]
            setup_name = self._document_setup["name"]

            async def run_setup() -> Any:
                try:
                    self._context = await _maybe_await(
                        setup_fn(
                            {
                                "project": self._project,
                                "projectContext": self._options.get(
                                    "projectContext"
                                ),
                                "document": {
                                    "documentId": self._document["documentId"],
                                    "documentRunId": self._document_run_id,
                                    "sourcePath": self._document.get(
                                        "sourcePath"
                                    ),
                                    "attemptIndex": self._options.get(
                                        "documentAttemptIndex", 0
                                    ),
                                },
                                "signal": self._signal,
                                "onTeardown": lambda teardown: (
                                    self._register_setup_teardown(
                                        setup_name, teardown
                                    )
                                ),
                            }
                        )
                    )
                    return self._context
                finally:
                    self._accepting_setup_teardowns = False

            try:
                await run_setup_with_timeout(
                    run_setup,
                    self._signal,
                    self._resource_scope.abort,
                    self._options.get("setupTimeoutMs"),
                )
            except Exception as error:
                self._host_errors.append(
                    {"phase": "setup", "error": as_execution_error(error)}
                )
        try:
            if not self._signal.aborted and not self._host_errors:
                await self._run_phase("beforeAll", self._before_all)
        except Exception as error:
            self._execution_errors.append(error)
            raise WorkflowExecutionFailure(
                self._create_result(), list(self._execution_errors)
            ) from error
        return self._create_result()

    def _register_setup_teardown(self, name: str, teardown: Any) -> None:
        if not self._accepting_setup_teardowns or not callable(teardown):
            raise WorkflowLifecycleError(
                "Document setup onTeardown() requires a function registered during setup.",
                {
                    "documentId": self._document["documentId"],
                    "documentRunId": self._document_run_id,
                },
            )
        self._node_teardown_stack.append(
            {
                "registrationIndex": len(self._node_teardown_stack),
                "node": name,
                "teardown": teardown,
                "host": True,
            }
        )

    async def finish(self) -> Dict[str, Any]:
        if self._finish_task is not None:
            return await self._finish_task
        if not self._started:
            raise WorkflowLifecycleError(
                "Workflow document runtime must start before it can finish.",
                {
                    "documentId": self._document["documentId"],
                    "documentRunId": self._document_run_id,
                },
            )
        self._finish_task = asyncio.ensure_future(self._finish_impl())
        return await self._finish_task

    async def _finish_impl(self) -> Dict[str, Any]:
        teardown_errors: List[Any] = []
        cleanup_execution_errors: List[Any] = []
        deferred_cleanup = False

        async def cleanup() -> None:
            prior_teardown_errors = len(teardown_errors)
            self._accepting_node_teardowns = False
            for entry in reversed(self._node_teardown_stack):
                try:
                    released = await _maybe_await(entry["teardown"]())
                    if isinstance(released, dict):
                        self._report_sources.extend(
                            released.get("reportSources") or []
                        )
                    for path in report_paths_from_teardown(released):
                        if path not in self._report_paths:
                            self._report_paths.append(path)
                except Exception as error:
                    if entry.get("host"):
                        failure = as_execution_error(error)
                        self._host_errors.append(
                            {"phase": "cleanup", "error": failure}
                        )
                        self._execution_errors.append(failure)
                        cleanup_execution_errors.append(error)
                        continue
                    teardown_errors.append(
                        NodeScopeTeardownError(
                            error,
                            {
                                "scope": "document",
                                "scopeId": self._document_run_id,
                                "node": entry["node"],
                                "registrationIndex": entry[
                                    "registrationIndex"
                                ],
                            },
                        )
                    )
            errors = [
                *cleanup_execution_errors,
                *teardown_errors[prior_teardown_errors:],
            ]
            if errors:
                raise WorkflowAggregateError(errors, "Document cleanup failed")

        async def before_cleanup(cleanup_signal: Any) -> None:
            try:
                if not any(
                    host.get("phase") == "setup"
                    for host in self._host_errors
                ):
                    await self._run_phase(
                        "afterAll", self._after_all, cleanup_signal
                    )
            except Exception as error:
                self._execution_errors.append(error)
                cleanup_execution_errors.append(error)

        try:
            if (
                self._document["lifecycle"]["afterAll"]
                or self._node_teardown_stack
                or (
                    self._options.get("setupTimeoutMs") is not None
                    and get_pending_scope_operations(self._signal)
                )
            ):
                await cleanup_scope_resources(
                    self._signal,
                    cleanup,
                    {
                        "totalTimeoutMs": _teardown_timeout(self._options),
                        "beforeCleanup": before_cleanup,
                        "onDeferredError": lambda error: logger.debug(
                            f"Deferred document cleanup failed: {error}"
                        ),
                    },
                )
            else:
                self._accepting_node_teardowns = False
        except Exception as error:
            deferred_cleanup = isinstance(error, ResourceCleanupDeferredError)
            if not deferred_cleanup:
                self._accepting_node_teardowns = False
            if (
                not deferred_cleanup
                and not teardown_errors
                and not cleanup_execution_errors
            ):
                teardown_errors.append(
                    NodeScopeTeardownError(
                        error,
                        {
                            "scope": "document",
                            "scopeId": self._document_run_id,
                            "node": "resource-drain",
                            "registrationIndex": -1,
                        },
                    )
                )
        finished_result = self._create_result(teardown_errors)
        on_result = self._options.get("onResult")
        try:
            await _call(on_result, finished_result)
        except Exception as error:
            self._execution_errors.append(error)
            finished_result = self._create_result(teardown_errors)
        self._resource_scope.dispose()
        if self._execution_errors:
            raise WorkflowExecutionFailure(
                finished_result, list(self._execution_errors)
            )
        return finished_result


def create_document_runtime(
    document: CollectedWorkflowDocument,
    options: Dict[str, Any],
) -> DocumentRuntime:
    return DocumentRuntime(document, options)


__all__ = ["DocumentRuntime", "create_document_runtime"]
