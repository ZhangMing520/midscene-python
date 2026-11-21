"""Project setup/teardown lifecycle (upstream engine/project-runtime.ts)."""

import asyncio
import datetime
import os
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from midscene.core.test_runner.engine._abort import (
    add_abort_listener,
    abort_reason,
    is_aborted,
)
from midscene.core.test_runner.engine.execution_failure import WorkflowAggregateError
from midscene.core.test_runner.engine.resource_operations import (
    ResourceCleanupDeferredError,
    cleanup_scope_resources,
    get_pending_scope_operations,
    get_resource_cleanup_snapshot,
    link_resource_signal,
    set_resource_operation_identity,
)
from midscene.core.test_runner.engine.setup_timeout import run_setup_with_timeout
from midscene.core.test_runner.errors import (
    ProjectSetupError,
    ProjectTeardownError,
    WorkflowLifecycleError,
)
from midscene.core.types import AbortSignal


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _setup_definition(setup: Any) -> Optional[Dict[str, Any]]:
    if setup is None:
        return None
    if isinstance(setup, dict):
        return {"name": setup.get("name", "setup"), "setup": setup.get("setup")}
    setup_fn = getattr(setup, "setup", None)
    if callable(setup_fn):
        return {"name": getattr(setup, "name", "setup"), "setup": setup_fn}
    if callable(setup):
        return {"name": getattr(setup, "__name__", "setup"), "setup": setup}
    raise TypeError("Project setup must be a definition or callable.")


def _teardown_timeout(options: Dict[str, Any]) -> Optional[float]:
    value = options.get("teardownTimeoutMs")
    if value is None:
        return None
    return value() if callable(value) else value


class ProjectRuntime:
    """Owns one project execution scope: setup, context and teardown."""

    def __init__(self, options: Dict[str, Any]) -> None:
        self._options = options
        self._project = options["project"]
        self._setup = _setup_definition(options.get("setup"))
        self._setup_timeout_ms = options.get("setupTimeoutMs")
        self._started_at = _now()
        self._controller = AbortSignal()
        parent_signal = options.get("signal")
        link_resource_signal(self._controller, parent_signal)
        set_resource_operation_identity(
            self._controller, {"scopeId": self._project.get("projectId")}
        )
        self._parent_disposer: Optional[Callable[[], None]] = None
        if parent_signal is not None:
            self._parent_disposer = add_abort_listener(
                parent_signal, lambda: self._controller.abort(abort_reason(parent_signal))
            )

        self._teardown_stack: List[Dict[str, Any]] = []
        self._context: Any = None
        self._setup_error: Optional[ProjectSetupError] = None
        self._started = False
        self._accepting_teardowns = self._setup is not None
        self._finish_task: Optional["asyncio.Future[Any]"] = None

    # -- runtime accessors -------------------------------------------------
    @property
    def context(self) -> Any:
        return self._context

    @property
    def signal(self) -> AbortSignal:
        return self._controller

    @property
    def can_run(self) -> bool:
        return self._started and self._setup_error is None and not is_aborted(
            self._controller
        )

    @property
    def project(self) -> Dict[str, Any]:
        return self._project

    # -- lifecycle ---------------------------------------------------------
    def _create_result(
        self,
        requested_status: str,
        teardown_errors: Optional[List[ProjectTeardownError]] = None,
    ) -> Dict[str, Any]:
        teardown_errors = teardown_errors or []
        ended_at = _now()
        cleanup = get_resource_cleanup_snapshot(self._controller)
        pending = get_pending_scope_operations(self._controller)
        failed = (
            requested_status == "failed"
            or self._setup_error is not None
            or bool(teardown_errors)
            or cleanup.get("status") in ("pending", "failed")
            or bool(pending)
        )
        result: Dict[str, Any] = {
            "projectName": self._project.get("name"),
            "status": "failed" if failed else "success",
            "startedAt": _iso(self._started_at),
            "endedAt": _iso(ended_at),
            "durationMs": max(
                0.0, (ended_at - self._started_at).total_seconds() * 1000
            ),
            "cleanup": cleanup,
        }
        if self._setup_error is not None:
            result["setupError"] = self._setup_error
        if teardown_errors:
            result["teardownErrors"] = list(teardown_errors)
        if pending:
            result["pendingOperations"] = pending
        return result

    def on_teardown(self, teardown: Any) -> None:
        if not self._accepting_teardowns:
            raise WorkflowLifecycleError(
                "onTeardown() can only be called while Project setup is running.",
                {"projectName": self._project.get("name")},
            )
        if not callable(teardown):
            raise WorkflowLifecycleError(
                "Project onTeardown() requires a teardown function.",
                {"projectName": self._project.get("name")},
            )
        self._teardown_stack.append(
            {"registrationIndex": len(self._teardown_stack), "teardown": teardown}
        )

    async def start(self) -> Dict[str, Any]:
        if self._started:
            raise WorkflowLifecycleError(
                "Project runtime has already started.",
                {"projectName": self._project.get("name")},
            )
        self._started = True
        if is_aborted(self._controller):
            self._accepting_teardowns = False
            return self._create_result("failed")
        if self._setup is not None:
            setup_fn = self._setup["setup"]

            async def run_setup() -> Any:
                try:
                    self._context = await _maybe_await(
                        setup_fn(
                            {
                                "project": self._project,
                                "env": dict(os.environ),
                                "signal": self._controller,
                                "onTeardown": self.on_teardown,
                            }
                        )
                    )
                    return self._context
                finally:
                    self._accepting_teardowns = False

            try:
                await run_setup_with_timeout(
                    run_setup,
                    self._controller,
                    lambda reason: self._controller.abort(reason),
                    self._setup_timeout_ms,
                )
            except Exception as error:
                self._setup_error = ProjectSetupError(
                    error, {"projectName": self._project.get("name")}
                )
        return self._create_result("failed" if self._setup_error else "success")

    async def finish(self, requested_status: str = "success") -> Dict[str, Any]:
        if self._finish_task is not None:
            return await self._finish_task
        if not self._started:
            raise WorkflowLifecycleError(
                "Project runtime must start before it can finish.",
                {"projectName": self._project.get("name")},
            )
        self._finish_task = asyncio.ensure_future(
            self._finish_impl(requested_status)
        )
        return await self._finish_task

    async def _finish_impl(self, requested_status: str) -> Dict[str, Any]:
        status_before_teardown = self._create_result(requested_status)["status"]
        teardown_errors: List[ProjectTeardownError] = []
        deferred_cleanup = False

        async def cleanup() -> None:
            prior_errors = len(teardown_errors)
            for entry in reversed(self._teardown_stack):
                try:
                    await _maybe_await(
                        entry["teardown"](
                            {
                                "project": self._project,
                                "context": self._context,
                                "status": status_before_teardown,
                                **(
                                    {"setupError": self._setup_error}
                                    if self._setup_error is not None
                                    else {}
                                ),
                            }
                        )
                    )
                except Exception as error:
                    teardown_errors.append(
                        ProjectTeardownError(
                            error,
                            {
                                "projectName": self._project.get("name"),
                                "registrationIndex": entry["registrationIndex"],
                            },
                        )
                    )
            if len(teardown_errors) > prior_errors:
                raise WorkflowAggregateError(
                    teardown_errors[prior_errors:], "Project cleanup failed"
                )

        try:
            if self._teardown_stack or (
                self._setup_timeout_ms is not None
                and get_pending_scope_operations(self._controller)
            ):
                await cleanup_scope_resources(
                    self._controller,
                    cleanup,
                    {
                        "totalTimeoutMs": _teardown_timeout(self._options),
                        "onDeferredError": lambda error: logger.debug(
                            f"Deferred Project cleanup failed: {error}"
                        ),
                    },
                )
        except Exception as error:
            deferred_cleanup = isinstance(error, ResourceCleanupDeferredError)
            if not deferred_cleanup and not teardown_errors:
                teardown_errors.append(
                    ProjectTeardownError(
                        error,
                        {
                            "projectName": self._project.get("name"),
                            "registrationIndex": -1,
                        },
                    )
                )
        if self._parent_disposer is not None:
            self._parent_disposer()
            self._parent_disposer = None
        return self._create_result(requested_status, teardown_errors)

    def abort(self, reason: Any = None) -> None:
        self._controller.abort(reason)


async def _maybe_await(value: Any) -> Any:
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


def create_project_runtime(options: Dict[str, Any]) -> ProjectRuntime:
    return ProjectRuntime(options)


__all__ = ["ProjectRuntime", "create_project_runtime"]
