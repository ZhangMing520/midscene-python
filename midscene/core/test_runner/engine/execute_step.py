"""Execute one workflow step (upstream test-runner/engine/execute-step.ts)."""

import asyncio
import copy
import datetime
import inspect
from collections.abc import Callable
from typing import Any

from midscene.core.test_runner.engine._abort import (
    abort_reason,
    add_abort_listener,
    is_aborted,
    link_abort,
    throw_if_aborted,
)
from midscene.core.test_runner.engine.resource_operations import (
    anonymous_resource,
    is_resource_admission_error,
    link_resource_signal,
    observe_resource_operations,
    record_operation,
    set_resource_operation_identity,
    track_resource_operation,
)
from midscene.core.test_runner.errors import (
    NodeExecutionError,
    NodeInputValidationError,
    StepTimeoutError,
    WorkflowError,
    is_node_execution_error,
    normalize_node_execution_error,
)
from midscene.core.test_runner.node.types import (
    NodeDefinition,
    NodeExecutionContext,
    NodeReportTrace,
    NodeResult,
)
from midscene.core.test_runner.parser.types import NormalizedStep
from midscene.core.types import AbortError

REPORT_SNAPSHOT_TIMEOUT_MS = 5000


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _iso(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _abort_exception(reason: Any) -> BaseException:
    if isinstance(reason, BaseException):
        return reason
    return AbortError(
        "Operation interrupted by an external abort signal.\n"
        f"Reason: {reason or 'signal already aborted'}"
    )


def validate_node_output(output: Any, node: str) -> Any:
    """Node output must be an object (or None) with an optional string summary."""
    if output is None:
        return None
    if isinstance(output, NodeResult):
        if output.summary is not None and not isinstance(output.summary, str):
            raise NodeExecutionError(
                node, TypeError("Node output summary must be a string.")
            )
        return output
    if not isinstance(output, dict):
        raise NodeExecutionError(
            node, TypeError("Node output must be an object or undefined.")
        )
    summary = output.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise NodeExecutionError(
            node, TypeError("Node output summary must be a string.")
        )
    return output


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _trace_payload(trace: Any) -> dict[str, Any]:
    if isinstance(trace, NodeReportTrace):
        payload: dict[str, Any] = {
            "type": trace.type,
            "executionId": trace.executionId,
        }
        if trace.metrics:
            payload["metrics"] = copy.deepcopy(trace.metrics)
        return payload
    if isinstance(trace, dict):
        payload = {
            "type": trace.get("type"),
            "executionId": trace.get("executionId"),
        }
        if trace.get("metrics"):
            payload["metrics"] = copy.deepcopy(trace["metrics"])
        return payload
    raise TypeError("Report trace must be an object.")


class _NodeReportCollector:
    """Collects execution traces and snapshot sources for the current Step."""

    def __init__(self, node: str) -> None:
        self._node = node
        self._traces: dict[str, dict[str, Any]] = {}
        self._captures: list[Callable[..., Any]] = []
        self._accepting = True

    def on_snapshot(self, capture: Callable[..., Any]) -> None:
        if not self._accepting or not callable(capture):
            raise WorkflowError(
                "A report snapshot callback must be registered while the Step is running.",
                {"code": "REPORT_SNAPSHOT_REGISTRATION"},
            )
        self._captures.append(capture)

    def add_trace(self, trace: Any) -> None:
        if not self._accepting:
            raise NodeExecutionError(
                self._node,
                RuntimeError(
                    "Report traces can only be added while the current Step is running."
                ),
            )
        try:
            payload = _trace_payload(trace)
        except TypeError as error:
            raise NodeExecutionError(self._node, error) from error
        if payload.get("type") != "midscene-execution":
            raise NodeExecutionError(
                self._node, TypeError('Report trace type must be "midscene-execution".')
            )
        execution_id = payload.get("executionId")
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise NodeExecutionError(
                self._node, TypeError("Report trace executionId must be non-empty.")
            )
        normalized: dict[str, Any] = {
            "type": "midscene-execution",
            "executionId": execution_id,
        }
        if payload.get("metrics"):
            normalized["metrics"] = copy.deepcopy(payload["metrics"])
        self._traces[f"{normalized['type']}:{execution_id}"] = normalized

    @staticmethod
    def _snapshot_error(error: Any) -> WorkflowError:
        if isinstance(error, WorkflowError):
            return error
        return WorkflowError(
            f"Agent report snapshot collection failed: {error}",
            {"code": "REPORT_SNAPSHOT_FAILED", "cause": error},
        )

    @staticmethod
    def _validate_source(source: Any) -> Any:
        if not isinstance(source, dict):
            raise TypeError(
                "Agent report capture must return sourcePath and a valid optional dumpPath."
            )
        source_path = source.get("sourcePath")
        if not isinstance(source_path, str) or not source_path.strip():
            raise TypeError(
                "Agent report capture must return sourcePath and a valid optional dumpPath."
            )
        dump_path = source.get("dumpPath")
        if dump_path is not None and (
            not isinstance(dump_path, str) or not dump_path.strip()
        ):
            raise TypeError(
                "Agent report capture must return sourcePath and a valid optional dumpPath."
            )
        captured = dict(source)
        if not dump_path:
            collection = dict(captured.get("collection") or {})
            collection.setdefault("status", "partial")
            collection.setdefault("capturedAt", _iso(_now()))
            collection.setdefault(
                "reason",
                "HTML report captures do not guarantee an immutable cutoff.",
            )
            captured["collection"] = collection
        return captured

    async def _capture_outcome(
        self,
        capture: Callable[..., Any],
        signal: Any,
        traces: list[dict[str, Any]],
        expired: "asyncio.Future[Any]",
    ) -> dict[str, Any]:
        task = asyncio.ensure_future(_maybe_await(capture(signal, traces)))
        try:
            done, _ = await asyncio.wait(
                {task, expired}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                try:
                    return {"source": self._validate_source(task.result())}
                except Exception as error:
                    return {"error": self._snapshot_error(error)}
            return {"error": expired.result()}
        finally:
            if not task.done():
                task.cancel()

    async def close(self) -> dict[str, Any]:
        self._accepting = False
        closed_traces = list(self._traces.values())
        if not self._captures:
            return {"traces": closed_traces}

        loop = asyncio.get_event_loop()
        from midscene.core.types import AbortSignal

        controller = AbortSignal()
        expired: asyncio.Future[Any] = loop.create_future()

        def on_expired() -> None:
            if expired.done():
                return
            error = WorkflowError(
                "Agent report snapshot collection timed out.",
                {
                    "code": "REPORT_SNAPSHOT_TIMEOUT",
                    "details": {"timeoutMs": REPORT_SNAPSHOT_TIMEOUT_MS},
                },
            )
            controller.abort(error)
            expired.set_result(error)

        timer = loop.call_later(REPORT_SNAPSHOT_TIMEOUT_MS / 1000.0, on_expired)
        try:
            outcomes = await asyncio.gather(
                *(
                    self._capture_outcome(capture, controller, closed_traces, expired)
                    for capture in self._captures
                )
            )
        finally:
            timer.cancel()
            if not expired.done():
                expired.cancel()

        sources = [outcome["source"] for outcome in outcomes if "source" in outcome]
        errors = [outcome["error"] for outcome in outcomes if "error" in outcome]
        report: dict[str, Any] = {"traces": closed_traces}
        if sources:
            report["sources"] = sources
        if errors:
            report["collectionErrors"] = errors
        return report


async def parse_node_input(node: NodeDefinition, input_value: dict[str, Any]) -> Any:
    """Validate the raw YAML input using the node's declared schema."""
    schema = node.input_schema
    if schema is None or isinstance(schema, dict):
        return input_value

    validator = getattr(schema, "model_validate", None) or getattr(
        schema, "parse_obj", None
    )
    if callable(validator):
        try:
            return validator(input_value)
        except Exception as error:
            issues: list[dict[str, Any]] = []
            errors_fn = getattr(error, "errors", None)
            if callable(errors_fn):
                try:
                    for item in errors_fn():
                        issues.append(
                            {
                                "path": ".".join(
                                    str(part) for part in item.get("loc", [])
                                ),
                                "message": item.get("msg", str(error)),
                            }
                        )
                except Exception:
                    issues = []
            if not issues:
                issues = [{"path": "", "message": str(error)}]
            raise NodeInputValidationError.from_validation_issues(
                node.name, issues
            ) from error
    if callable(schema):
        return await _maybe_await(schema(input_value))
    raise NodeInputValidationError(
        f'Node "{node.name}" inputSchema must be a callable or object schema.',
        {"node": node.name},
    )


async def execute_node(
    step: NormalizedStep,
    execute: Callable[[Any], Any],
    phase: str,
    step_index: int,
    options: dict[str, Any],
) -> dict[str, Any]:
    started_at = _now()
    meta = step.get("meta") or {}
    from midscene.core.types import AbortSignal

    controller = AbortSignal()
    parent_signal = options.get("parentSignal")
    link_resource_signal(controller, parent_signal)
    set_resource_operation_identity(controller, options["identity"])
    stop_observing = observe_resource_operations(controller, options["onEvent"])

    parent_disposer: Callable[[], None] | None = None
    if parent_signal is not None:
        parent_disposer = link_abort(controller, parent_signal)

    timeout_ms = meta.get("timeoutMs", options.get("defaultTimeoutMs"))
    loop = asyncio.get_event_loop()

    async def run() -> Any:
        throw_if_aborted(controller)
        return await _maybe_await(execute(controller))

    execution = asyncio.ensure_future(run())
    observation = record_operation(execution, controller, "node")
    # A custom node's teardown cannot dispose what its actual execution still uses.
    track_resource_operation(
        anonymous_resource(), execution, controller, "node", observation
    )

    returned_status = "failed"
    abort_future: asyncio.Future[Any] = loop.create_future()

    def on_abort() -> None:
        if not abort_future.done():
            abort_future.set_result(True)

    abort_disposer = add_abort_listener(controller, on_abort)

    timeout_future: asyncio.Future[Any] | None = None
    timer = None
    if timeout_ms is not None:

        def on_timeout() -> None:
            if timeout_future is None or timeout_future.done():
                return
            if is_aborted(controller):
                timeout_future.set_result(abort_reason(controller))
                return
            error = StepTimeoutError(timeout_ms, step.get("node"))
            controller.abort(error)
            timeout_future.set_result(error)

        timeout_future = loop.create_future()
        timer = loop.call_later(timeout_ms / 1000.0, on_timeout)

    waiters = {execution, abort_future}
    if timeout_future is not None:
        waiters.add(timeout_future)

    try:
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if not execution.done():
                # Abort listeners run synchronously. Wait one task before raising
                # so a cooperative node can settle in response to the abort first.
                await asyncio.sleep(0)
            if execution.done():
                output = execution.result()
            else:
                raise _abort_exception(abort_reason(controller))
            output = validate_node_output(output, step.get("node"))
            returned_status = "success"
            ended_at = _now()
            result: dict[str, Any] = {
                "node": step.get("node"),
                "phase": phase,
                "stepIndex": step_index,
                "input": step.get("input"),
                "meta": meta,
                "startedAt": _iso(started_at),
                "endedAt": _iso(ended_at),
                "durationMs": max(0.0, (ended_at - started_at).total_seconds() * 1000),
                "status": "success",
                "continuedAfterError": False,
            }
            if output is not None:
                result["output"] = output
            return result
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            if is_resource_admission_error(error):
                returned_status = "not-run"
                not_run: dict[str, Any] = {
                    "node": step.get("node"),
                    "phase": phase,
                    "stepIndex": step_index,
                    "input": step.get("input"),
                    "meta": meta,
                    "status": "not-run",
                    "notRunReason": str(error),
                    "continuedAfterError": bool(meta.get("continueOnError")),
                    "error": error,
                }
                blocked_by = getattr(error, "blocked_by", None)
                if blocked_by:
                    not_run["blockedBy"] = blocked_by
                return not_run

            output = None
            failure: Any = error
            if (
                is_node_execution_error(error)
                and getattr(error, "output", None) is not None
            ):
                try:
                    output = validate_node_output(error.output, step.get("node"))
                except Exception as validation_error:
                    failure = validation_error
            ended_at = _now()
            failed: dict[str, Any] = {
                "node": step.get("node"),
                "phase": phase,
                "stepIndex": step_index,
                "input": step.get("input"),
                "meta": meta,
                "startedAt": _iso(started_at),
                "endedAt": _iso(ended_at),
                "durationMs": max(0.0, (ended_at - started_at).total_seconds() * 1000),
                "status": "failed",
                "continuedAfterError": bool(meta.get("continueOnError")),
                "error": normalize_node_execution_error(failure, step.get("node")),
            }
            if output is not None:
                failed["output"] = output
            return failed

    finally:
        observation.runner_returned(returned_status)
        stop_observing()
        if timer is not None:
            timer.cancel()
        abort_disposer()
        if parent_disposer is not None:
            parent_disposer()
        if not abort_future.done():
            abort_future.cancel()
        if timeout_future is not None and not timeout_future.done():
            timeout_future.cancel()


async def execute_step(
    step: NormalizedStep,
    node: NodeDefinition,
    target: dict[str, Any],
    context: Any,
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    execution = execution or {}
    scope = target["scope"]
    if scope == "case":
        case = target["case"]
        phase = case.get("phase")
        step_index = case.get("stepIndex")
        scope_id = case.get("runId")
        document = None
    else:
        document = target["document"]
        phase = document.get("phase")
        step_index = document.get("stepIndex")
        scope_id = document.get("documentRunId")
        case = None

    collector = _NodeReportCollector(step.get("node"))
    events: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None

    async def run_node(signal: Any) -> Any:
        input_value = await parse_node_input(node, step.get("input") or {})
        throw_if_aborted(signal)

        def on_teardown(teardown: Callable[..., Any]) -> None:
            if execution.get("onTeardown") is None:
                raise NodeExecutionError(
                    step.get("node"),
                    RuntimeError(
                        "The current execution scope cannot register teardown."
                    ),
                )
            execution["onTeardown"](step.get("node"), teardown)

        execution_context = NodeExecutionContext(
            input=input_value,
            meta=step.get("meta") or {},
            signal=signal,
            context=context,
            on_teardown=on_teardown,
            report=collector,
            scope=scope,
            case=case,
            document=document,
        )
        return await _maybe_await(node.execute(execution_context))

    try:
        result = await execute_node(
            step,
            run_node,
            phase,
            step_index,
            {
                "parentSignal": execution.get("signal"),
                "defaultTimeoutMs": execution.get("defaultTimeoutMs"),
                "identity": {
                    "scopeId": scope_id,
                    "stepId": f"{scope_id}:{phase}:{step_index}",
                    "node": step.get("node"),
                },
                "onEvent": events.append,
            },
        )
    finally:
        report = await collector.close()
        if result is not None:
            result["operations"] = {
                "capturedAt": _iso(_now()),
                "events": list(events),
            }
            if (
                report.get("traces")
                or report.get("sources")
                or report.get("collectionErrors")
            ):
                result["report"] = report

    if result is None:
        raise NodeExecutionError(
            step.get("node"),
            RuntimeError("Step execution completed without a result."),
        )
    return result


__all__ = [
    "REPORT_SNAPSHOT_TIMEOUT_MS",
    "execute_node",
    "execute_step",
    "parse_node_input",
    "validate_node_output",
]
