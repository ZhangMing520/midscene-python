"""Execute one collected Case (upstream engine/run-collected-case.ts)."""

import datetime
import inspect
import uuid
from collections.abc import Callable
from typing import Any

from loguru import logger

from midscene.core.test_runner.engine.execute_step import execute_step
from midscene.core.test_runner.engine.execution_failure import (
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
from midscene.core.test_runner.errors import (
    NodeScopeTeardownError,
    WorkflowLifecycleError,
)
from midscene.core.test_runner.parser.types import CollectedCase


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _iso(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _call(callback: Callable[..., Any] | None, *args: Any) -> None:
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result


async def run_collected_case(
    collected_case: CollectedCase,
    options: dict[str, Any],
) -> dict[str, Any]:
    definition = collected_case["definition"]
    phases = {
        "beforeEach": list(options.get("beforeEach") or []),
        "steps": list(definition.get("steps") or []),
        "afterEach": list(options.get("afterEach") or []),
    }
    resolve_node = options["resolveNode"]
    nodes = {
        phase: [resolve_node(step.get("node")) for step in steps]
        for phase, steps in phases.items()
    }

    resource_scope = create_resource_scope(options.get("signal"))
    scope_signal = resource_scope.signal
    create_run_id = options.get("createRunId")
    run_id = create_run_id() if create_run_id else uuid.uuid4().hex
    started_at = _now()
    set_resource_operation_identity(scope_signal, {"scopeId": run_id})

    beforeEach: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    afterEach: list[dict[str, Any]] = []
    captured_sources: dict[str, dict[str, Any]] = {}
    teardown_stack: list[dict[str, Any]] = []
    accepting_teardowns = True

    def on_teardown(node: str, teardown: Any) -> None:
        nonlocal accepting_teardowns
        if not accepting_teardowns:
            raise WorkflowLifecycleError(
                "Node teardown can only be registered while a case attempt is running.",
                {"runId": run_id, "node": node},
            )
        if not callable(teardown):
            raise WorkflowLifecycleError(
                "Node onTeardown() requires a teardown function.",
                {"runId": run_id, "node": node},
            )
        teardown_stack.append(
            {
                "registrationIndex": len(teardown_stack),
                "node": node,
                "teardown": teardown,
            }
        )

    async def run_phase(
        phase: str,
        results: list[dict[str, Any]],
        signal: Any = None,
    ) -> None:
        execution_signal = scope_signal if signal is None else signal
        phase_steps = phases[phase]
        for step_index, step in enumerate(phase_steps):
            # A Step timeout ends the Runner's wait, not the underlying operation.
            # Recovery belongs between Steps, outside the next Step's timeout budget.
            wait_for_previous_ms = (
                await recover_cancelled_scope_resources(execution_signal)
                if step_index > 0
                else 0
            )
            case_context = {
                "caseId": collected_case["caseId"],
                "runId": run_id,
                "projectName": options.get("projectName")
                or collected_case.get("projectId"),
                "attemptIndex": options.get("attemptIndex", 0),
                "name": definition.get("name"),
                "sourcePath": collected_case.get("sourcePath"),
                "caseIndex": collected_case.get("caseIndex"),
                "phase": phase,
                "stepIndex": step_index,
            }
            step_info = {
                "scope": "case",
                "node": step.get("node"),
                "stepCount": len(phase_steps),
                "case": case_context,
            }
            await _call(options.get("onStepStart"), step_info)
            result = await execute_step(
                step,
                nodes[phase][step_index],
                {"scope": "case", "case": case_context},
                options.get("context"),
                {
                    "signal": execution_signal,
                    "defaultTimeoutMs": options.get("defaultTimeoutMs"),
                    "onTeardown": on_teardown,
                },
            )
            if wait_for_previous_ms > 0:
                result["waitForPreviousOperationMs"] = wait_for_previous_ms
            results.append(result)
            for source in (result.get("report") or {}).get("sources") or []:
                caption = (
                    f"{source.get('sourcePath')}\u0000{source.get('dumpPath') or ''}"
                )
                captured_sources[caption] = source
            await _call(options.get("onStepResult"), step_info, result)
            if result.get("status") != "success" and not result.get(
                "continuedAfterError"
            ):
                break

    execution_errors: list[Any] = []
    try:
        await run_phase("beforeEach", beforeEach)
        if not any(step.get("status") != "success" for step in beforeEach):
            await run_phase("steps", steps)
    except Exception as error:
        execution_errors.append(error)

    teardown_errors: list[NodeScopeTeardownError] = []
    report_paths: list[str] = []
    report_sources: list[dict[str, Any]] = []
    cleanup_execution_errors: list[Any] = []
    deferred_cleanup = False

    async def cleanup() -> None:
        nonlocal accepting_teardowns
        prior_teardown_errors = len(teardown_errors)
        accepting_teardowns = False
        for entry in reversed(teardown_stack):
            try:
                released = await _maybe_await(entry["teardown"]())
                if isinstance(released, dict):
                    report_sources.extend(released.get("reportSources") or [])
                for path in report_paths_from_teardown(released):
                    if path not in report_paths:
                        report_paths.append(path)
            except Exception as error:
                teardown_errors.append(
                    NodeScopeTeardownError(
                        error,
                        {
                            "scope": "case",
                            "scopeId": run_id,
                            "node": entry["node"],
                            "registrationIndex": entry["registrationIndex"],
                        },
                    )
                )
        errors = [
            *cleanup_execution_errors,
            *teardown_errors[prior_teardown_errors:],
        ]
        if errors:
            from midscene.core.test_runner.engine.execution_failure import (
                WorkflowAggregateError,
            )

            raise WorkflowAggregateError(errors, "Case cleanup failed")

    async def before_cleanup(cleanup_signal: Any) -> None:
        try:
            await run_phase("afterEach", afterEach, cleanup_signal)
        except Exception as error:
            execution_errors.append(error)
            cleanup_execution_errors.append(error)

    try:
        if phases["afterEach"] or teardown_stack:
            await cleanup_scope_resources(
                scope_signal,
                cleanup,
                {
                    "totalTimeoutMs": _teardown_timeout(options),
                    "beforeCleanup": before_cleanup,
                    "onDeferredError": lambda error: logger.debug(
                        f"Deferred Case cleanup failed: {error}"
                    ),
                },
            )
        else:
            accepting_teardowns = False
    except Exception as error:
        deferred_cleanup = isinstance(error, ResourceCleanupDeferredError)
        if not deferred_cleanup:
            accepting_teardowns = False
        if (
            not deferred_cleanup
            and not teardown_errors
            and not cleanup_execution_errors
        ):
            teardown_errors.append(
                NodeScopeTeardownError(
                    error,
                    {
                        "scope": "case",
                        "scopeId": run_id,
                        "node": "resource-drain",
                        "registrationIndex": -1,
                    },
                )
            )

    ended_at = _now()
    cleanup_snapshot = get_resource_cleanup_snapshot(scope_signal)
    pending_operations = get_pending_scope_operations(scope_signal)
    phase_results = {
        "beforeEach": phase_result(len(phases["beforeEach"]), beforeEach),
        "steps": phase_result(len(phases["steps"]), steps),
        "afterEach": phase_result(len(phases["afterEach"]), afterEach),
    }
    has_failed_phase = any(
        phase.get("status") == "failed" for phase in phase_results.values()
    )
    has_not_run_phase = any(
        phase.get("status") == "not-run" for phase in phase_results.values()
    )
    failed = (
        bool(execution_errors)
        or any(step.get("status") != "success" for step in beforeEach)
        or any(step.get("status") != "success" for step in steps)
        or any(step.get("status") != "success" for step in afterEach)
        or cleanup_snapshot.get("status") in ("pending", "failed")
        or bool(pending_operations)
        or bool(teardown_errors)
    )
    result: dict[str, Any] = {
        "caseId": collected_case["caseId"],
        "runId": run_id,
        "projectName": options.get("projectName") or collected_case.get("projectId"),
        "attemptIndex": options.get("attemptIndex", 0),
        "name": definition.get("name"),
        "sourcePath": collected_case.get("sourcePath"),
        "caseIndex": collected_case.get("caseIndex"),
        "status": "failed" if failed else "success",
        "beforeEach": list(beforeEach),
        "steps": list(steps),
        "afterEach": list(afterEach),
        "executionStatus": (
            "failed"
            if has_failed_phase
            else "not-run"
            if has_not_run_phase
            else "success"
        ),
        "phases": phase_results,
        "cleanup": cleanup_snapshot,
        "startedAt": _iso(started_at),
        "endedAt": _iso(ended_at),
        "durationMs": max(0.0, (ended_at - started_at).total_seconds() * 1000),
    }
    if pending_operations:
        result["pendingOperations"] = pending_operations
    if execution_errors:
        result["executionErrors"] = [
            as_execution_error(error) for error in execution_errors
        ]
    if teardown_errors:
        result["teardownErrors"] = list(teardown_errors)
    if report_paths:
        result["reportPaths"] = list(report_paths)
    if captured_sources or report_sources:
        result["reportSources"] = [
            *captured_sources.values(),
            *report_sources,
        ]
    if options.get("reportScopeId"):
        result["reportScopeId"] = options["reportScopeId"]

    try:
        await _call(options.get("onResult"), result)
    except Exception as error:
        execution_errors.append(error)
        result["status"] = "failed"
        result["executionErrors"] = [
            as_execution_error(item) for item in execution_errors
        ]
    resource_scope.dispose()
    if execution_errors:
        raise WorkflowExecutionFailure(result, execution_errors)
    return result


def _teardown_timeout(options: dict[str, Any]) -> float | None:
    value = options.get("teardownTimeoutMs")
    if value is None:
        return None
    return value() if callable(value) else value


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = ["run_collected_case"]
