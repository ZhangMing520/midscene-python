"""Legacy YAML workflow runtime (upstream yaml/legacy-yaml-runtime.ts).

Runs legacy YAML tasks through the shared workflow engine while preserving the
old YAML boundary: task-index lookup, error recording, report traces and
result publication.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from loguru import logger

from midscene.core.agent.action_readiness import is_action_readiness_error
from midscene.core.dump.task_status import derive_case_status
from midscene.core.test_runner.engine.resource_operations import (
    admit_resource_operation,
    track_resource_operation,
    wait_for_resource_idle,
)
from midscene.core.test_runner.engine.run_workflow_document import (
    run_workflow_document,
)
from midscene.core.test_runner.node.define_node import define_node
from midscene.core.test_runner.node.types import NodeResult
from midscene.core.test_runner.parser.types import CollectedWorkflowDocument
from midscene.core.yaml.execution_session import (
    enter_yaml_action,
    run_in_yaml_execution_context,
)
from midscene.core.yaml.test_runner_compat import (
    collect_legacy_yaml_document,
    collect_legacy_yaml_task_document,
)
from midscene.core.yaml.test_runner_nodes import (
    LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    AgentTestRunnerNodeExecutionContext,
    get_legacy_yaml_result_data,
)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _report_executions(agent: Any) -> list[Any]:
    builder = getattr(agent, "_report_builder", None)
    if builder is None:
        getter = getattr(agent, "_get_report_builder", None)
        if callable(getter):
            try:
                builder = getter()
            except Exception:
                builder = None
    dump = getattr(builder, "dump", None) if builder is not None else None
    if isinstance(dump, dict):
        return list(dump.get("executions") or [])
    return []


def _has_failed_report_execution_since(agent: Any, execution_count_before: int) -> bool:
    executions = _report_executions(agent)[execution_count_before:]
    return derive_case_status(executions) == "failed"


async def _record_yaml_task_error(
    agent: Any, task: dict[str, Any], flow_item_index: int, error: BaseException
) -> None:
    recorder = getattr(agent, "record_error_to_report", None)
    if not callable(recorder):
        return
    task_name = task.get("name")
    try:
        await recorder(
            f"YAML task failed - {task_name}",
            {
                "error": error,
                "content": (
                    f"Step {flow_item_index} failed while running YAML task "
                    f'"{task_name}".'
                ),
            },
        )
    except Exception as report_error:  # noqa: BLE001 - reporting must not mask failure
        logger.debug(f"failed to record yaml error to report: {report_error}")


@dataclass
class LegacyYamlRuntimeOptions:
    agent: Any
    action_space: list[Any]
    source_path: str
    set_result: Callable[[str | None, Any], Any]


def _create_legacy_yaml_node_resolver(
    options: LegacyYamlRuntimeOptions,
    resolve_task: Callable[[int], dict[str, Any] | None],
    record_task_errors: bool,
    capture_report_traces: bool,
) -> Callable[[str], Any]:
    definitions = {
        definition.name: definition
        for definition in LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS
    }
    nodes: dict[str, Any] = {}

    def resolve(name: str) -> Any:
        existing = nodes.get(name)
        if existing is not None:
            return existing

        definition = definitions.get(name)
        if definition is None:
            raise AssertionError(f"Unknown Agent Node: {name}")

        async def execute(ctx: Any) -> Any:
            return await run_in_yaml_execution_context(
                lambda: _run_node(
                    ctx,
                    definition,
                    resolve_task,
                    record_task_errors,
                    capture_report_traces,
                )
            )

        node = define_node(
            name,
            execute,
            input_schema=definition.input_schema,
        )
        nodes[name] = node
        return node

    async def _run_node(
        ctx: Any,
        definition: Any,
        resolve_task_fn: Callable[[int], dict[str, Any] | None],
        record_errors: bool,
        capture_traces: bool,
    ) -> Any:
        ctx.signal.throw_if_aborted()
        admit_resource_operation(options.agent, ctx.signal, False)
        if ctx.scope != "case":
            raise AssertionError("YAML task requires a Case scope")
        task_index = ctx.case.get("caseIndex")
        flow_item_index = ctx.case.get("stepIndex")
        task = resolve_task_fn(task_index)
        if task is None:
            raise AssertionError(f"missing YAML task at index {task_index}")
        if not task.get("flow"):
            raise AssertionError("missing flow in task")

        execution_count_before_step = len(_report_executions(options.agent))
        remove_dump_listener = None
        add_dump_listener = (
            getattr(options.agent, "add_dump_update_listener", None)
            if capture_traces
            else None
        )
        if callable(add_dump_listener):

            def listener(_dump: Any, execution: dict[str, Any] | None = None) -> None:
                if not ctx.signal.aborted and execution and execution.get("id"):
                    ctx.report.add_trace(
                        {
                            "type": "midscene-execution",
                            "executionId": execution["id"],
                        }
                    )

            remove_dump_listener = add_dump_listener(listener)

        listening = True

        def remove_listener() -> None:
            nonlocal listening
            if not listening:
                return
            listening = False
            if callable(remove_dump_listener):
                remove_dump_listener()

        async def invoke() -> Any:
            ctx.signal.throw_if_aborted()
            return await _maybe_await(
                definition.execute(
                    options.agent,
                    ctx.input,
                    AgentTestRunnerNodeExecutionContext(signal=ctx.signal),
                )
            )

        operation = track_resource_operation(options.agent, invoke(), ctx.signal)
        leave_action = enter_yaml_action(options.agent, ctx.signal)

        def on_abort() -> None:
            remove_listener()

        ctx.signal.add_event_listener("abort", on_abort, once=True)
        try:
            return await operation
        except BaseException as error:
            report_already_contains_failure = _has_failed_report_execution_since(
                options.agent, execution_count_before_step
            )
            if (
                not ctx.signal.aborted
                and record_errors
                and not report_already_contains_failure
            ):
                await _record_yaml_task_error(
                    options.agent, task, flow_item_index, error
                )
            raise
        finally:
            ctx.signal.remove_event_listener("abort", on_abort)
            remove_listener()
            leave_action()

    return resolve


async def _run_legacy_yaml_document(
    document: CollectedWorkflowDocument,
    options: LegacyYamlRuntimeOptions,
    resolve_task: Callable[[int], dict[str, Any] | None],
    record_task_errors: bool,
    capture_report_traces: bool,
    run_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_options = dict(run_options or {})
    provided_is_fatal = run_options.get("isFatalError")
    provided_on_step_result = run_options.get("onStepResult")

    def is_fatal_error(run: dict[str, Any]) -> bool:
        steps = [
            *(run.get("beforeEach") or []),
            *(run.get("steps") or []),
            *(run.get("afterEach") or []),
        ]
        if any(
            is_action_readiness_error(getattr(step.get("error"), "cause", None))
            for step in steps
        ):
            return True
        return bool(provided_is_fatal(run)) if provided_is_fatal else False

    async def on_step_result(info: dict[str, Any], result: dict[str, Any]) -> None:
        meta = result.get("meta") or {}
        output = result.get("output")
        has_data = isinstance(output, NodeResult) or (
            isinstance(output, dict) and "data" in output
        )
        if meta.get("captureResult") and output is not None and has_data:
            # Publication follows the recorded action. The Node result is never mutated.
            await _maybe_await(
                options.set_result(
                    meta.get("resultName"),
                    get_legacy_yaml_result_data(cast(str, result.get("node")), output),
                )
            )
        if provided_on_step_result is not None:
            await _maybe_await(provided_on_step_result(info, result))

    run_options.update(
        {
            "isFatalError": is_fatal_error,
            "onStepResult": on_step_result,
            "resolveNode": _create_legacy_yaml_node_resolver(
                options, resolve_task, record_task_errors, capture_report_traces
            ),
            "projectContext": options.agent,
            # Legacy CLI retry recreates the whole player and Agent outside this
            # runtime, so the shared kernel must not retry a Case here.
            "retry": 0,
            # One legacy YAML file owns one Agent report shared by all its tasks.
            "resolveCaseReportScopeId": lambda _case, _attempt, document_run_id: (
                document_run_id
            ),
        }
    )
    return await run_workflow_document(document, run_options)


@dataclass
class LegacyYamlRuntime:
    """Run one legacy YAML script or task through the shared engine."""

    options: LegacyYamlRuntimeOptions

    async def wait_for_idle(self) -> None:
        """Wait before releasing an Agent whose non-cooperative action was aborted."""
        await wait_for_resource_idle(self.options.agent)

    async def run_script(
        self,
        script: dict[str, Any],
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_options = dict(run_options or {})
        document = cast(
            CollectedWorkflowDocument,
            run_options.get("document")
            or collect_legacy_yaml_document(
                script, self.options.source_path, self.options.action_space
            ),
        )
        tasks = script.get("tasks") or []
        return await _run_legacy_yaml_document(
            document,
            self.options,
            lambda task_index: (
                tasks[task_index]
                if isinstance(task_index, int) and 0 <= task_index < len(tasks)
                else None
            ),
            True,
            True,
            run_options,
        )

    async def run_task(
        self,
        task: dict[str, Any],
        task_index: int,
        run_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        document = collect_legacy_yaml_task_document(
            task,
            task_index,
            self.options.source_path,
            self.options.action_space,
        )
        return await _run_legacy_yaml_document(
            document,
            self.options,
            lambda _task_index: task,
            False,
            False,
            run_options,
        )


def create_legacy_yaml_runtime(options: dict[str, Any]) -> LegacyYamlRuntime:
    """Build a runtime from `{agent, actionSpace, sourcePath, setResult}`."""
    return LegacyYamlRuntime(
        LegacyYamlRuntimeOptions(
            agent=options["agent"],
            action_space=list(options.get("actionSpace") or []),
            source_path=options.get("sourcePath") or "<inline-yaml>",
            set_result=options["setResult"],
        )
    )


def legacy_yaml_outcome_error(outcome: dict[str, Any]) -> BaseException:
    """Return the original step failure behind a failed Case outcome."""
    run = outcome.get("run") or {}
    failed_step = next(
        (
            step
            for phase in ("beforeEach", "steps", "afterEach")
            for step in run.get(phase) or []
            if step.get("status") != "success"
        ),
        None,
    )
    error = failed_step.get("error") if failed_step else None
    cause = getattr(error, "cause", None)
    if getattr(error, "code", None) == "NODE_EXECUTION_ERROR" and cause is not None:
        return cast(BaseException, cause)
    if error is not None:
        return cast(BaseException, error)
    return RuntimeError(f'Task "{outcome.get("name")}" failed')


__all__ = [
    "LegacyYamlRuntime",
    "LegacyYamlRuntimeOptions",
    "create_legacy_yaml_runtime",
    "legacy_yaml_outcome_error",
]
