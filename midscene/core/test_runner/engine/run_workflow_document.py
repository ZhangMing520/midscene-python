"""Run a whole workflow document (upstream engine/run-workflow-document.ts)."""

import inspect
from typing import Any, Callable, Dict, List, Optional

from midscene.core.test_runner.engine.document_runtime import (
    create_document_runtime,
)
from midscene.core.test_runner.engine.execution_failure import (
    WorkflowAggregateError,
    WorkflowExecutionFailure,
    as_execution_error,
)
from midscene.core.test_runner.engine.result_metadata import decide_retry
from midscene.core.test_runner.engine.run_collected_case import run_collected_case
from midscene.core.test_runner.errors import is_resource_recovery_error
from midscene.core.test_runner.parser.types import CollectedCase, CollectedWorkflowDocument
from midscene.core.types import AbortSignal


async def _call(callback: Optional[Callable[..., Any]], *args: Any) -> Any:
    if callback is None:
        return None
    result = callback(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def _as_not_run(
    collected_case: CollectedCase,
    project_name: str,
    reason: str,
) -> Dict[str, Any]:
    definition = collected_case["definition"]
    outcome: Dict[str, Any] = {
        "caseId": collected_case["caseId"],
        "projectName": project_name,
        "name": definition.get("name"),
        "sourcePath": collected_case.get("sourcePath"),
        "caseIndex": collected_case.get("caseIndex"),
        "status": "not-run",
        "notRunReason": reason,
    }
    if definition.get("onFailure"):
        outcome["onFailure"] = definition["onFailure"]
    return outcome


def _case_outcome(
    collected_case: CollectedCase,
    project_name: str,
    status: str,
    run: Dict[str, Any],
    attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    definition = collected_case["definition"]
    outcome: Dict[str, Any] = {
        "caseId": collected_case["caseId"],
        "projectName": project_name,
        "name": definition.get("name"),
        "sourcePath": collected_case.get("sourcePath"),
        "caseIndex": collected_case.get("caseIndex"),
        "status": status,
        "run": run,
        "attempts": attempts,
    }
    if definition.get("onFailure"):
        outcome["onFailure"] = definition["onFailure"]
    return outcome


async def run_workflow_document(
    document: CollectedWorkflowDocument,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    signal = options.get("signal") or AbortSignal()
    create_document_run_id = options.get("createDocumentRunId")
    create_case_run_id = options.get("createCaseRunId")
    project = options.get("project") or {}
    project_name = project.get("name") or document.get("projectId")
    retry = options.get(
        "retry", project.get("retry", 0)
    )
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        raise TypeError("Workflow document retry must be a non-negative integer.")

    runtime = create_document_runtime(
        document,
        {
            "plan": options.get("plan"),
            "documentSetup": options.get("documentSetup"),
            "setupTimeoutMs": options.get("setupTimeoutMs"),
            "teardownTimeoutMs": options.get("teardownTimeoutMs"),
            "documentAttemptIndex": options.get("documentAttemptIndex"),
            "resolveNode": options["resolveNode"],
            "project": options.get("project"),
            "projectContext": options.get("projectContext"),
            "signal": signal,
            "defaultTimeoutMs": options.get("defaultTimeoutMs"),
            "onStepStart": options.get("onStepStart"),
            "onStepResult": options.get("onStepResult"),
            "createDocumentRunId": (
                (lambda: create_document_run_id(document))
                if create_document_run_id
                else None
            ),
        },
    )

    async def on_document_result(result: Dict[str, Any]) -> None:
        setup = options.get("documentSetup")
        if setup is not None:
            on_document_result_fn = (
                setup.get("onDocumentResult")
                if isinstance(setup, dict)
                else getattr(setup, "onDocumentResult", None)
            )
            if on_document_result_fn is not None:
                await _call(on_document_result_fn, result, runtime.context)
        await _call(options.get("onDocumentResult"), result)

    runtime._options["onResult"] = on_document_result

    cases: List[Dict[str, Any]] = []
    runtime_started = False
    document_result: Optional[Dict[str, Any]] = None
    execution_errors: List[Any] = []
    fatal_error = False
    document_stop_reason: Optional[str] = None

    def stop_reason() -> str:
        return options.get("stopReason")() if options.get("stopReason") else "interrupted"

    try:
        runtime_started = True
        started_document = await runtime.start()

        if not runtime.can_run_cases:
            reason = (
                stop_reason()
                if signal.aborted
                else "document-start-failed"
            )
            for collected_case in document["cases"]:
                cases.append(_as_not_run(collected_case, project_name, reason))
        else:
            for collected_case in document["cases"]:
                should_stop = options.get("shouldStop")
                if (
                    document_stop_reason
                    or fatal_error
                    or signal.aborted
                    or (should_stop() if should_stop else False)
                ):
                    if signal.aborted:
                        reason = stop_reason()
                    elif fatal_error:
                        reason = "fatal-error"
                    else:
                        reason = document_stop_reason or stop_reason()
                    outcome = _as_not_run(
                        collected_case, project_name, reason
                    )
                    cases.append(outcome)
                    await _call(options.get("onCaseOutcome"), outcome)
                    continue

                await _call(options.get("onCaseStart"), collected_case)
                attempts: List[Dict[str, Any]] = []
                for attempt_index in range(retry + 1):
                    attempt_fatal_error = False
                    attempt_failure: Optional[WorkflowExecutionFailure] = None

                    def make_on_result(index: int):
                        async def on_result(result: Dict[str, Any]) -> None:
                            nonlocal attempt_fatal_error
                            is_fatal = options.get("isFatalError")
                            attempt_fatal_error = (
                                bool(is_fatal(result)) if is_fatal else False
                            )
                            cleanup = result.get("cleanup") or {}
                            result["retryDecision"] = decide_retry(
                                {
                                    "scope": "case",
                                    "retryCount": retry,
                                    "attemptIndex": index,
                                    "status": result.get("status"),
                                    "cleanupPending": cleanup.get("status")
                                    == "pending",
                                    "operationPending": bool(
                                        result.get("pendingOperations")
                                    ),
                                    "cleanupFailed": cleanup.get("status")
                                    == "failed"
                                    or bool(result.get("teardownErrors")),
                                    "infrastructureError": any(
                                        not is_resource_recovery_error(error)
                                        for error in result.get(
                                            "executionErrors"
                                        )
                                        or []
                                    ),
                                    "fatalError": attempt_fatal_error,
                                    "interrupted": signal.aborted,
                                    "shouldStop": (
                                        options.get("shouldStop")()
                                        if options.get("shouldStop")
                                        else False
                                    ),
                                }
                            )
                            await _call(options.get("onCaseResult"), result)

                        return on_result

                    resolve_scope = options.get("resolveCaseReportScopeId")
                    try:
                        run = await run_collected_case(
                            collected_case,
                            {
                                "resolveNode": options["resolveNode"],
                                "beforeEach": document["lifecycle"]["beforeEach"],
                                "afterEach": document["lifecycle"]["afterEach"],
                                "context": runtime.context,
                                "projectName": project_name,
                                "attemptIndex": attempt_index,
                                "signal": runtime.signal,
                                "defaultTimeoutMs": options.get(
                                    "defaultTimeoutMs"
                                ),
                                "teardownTimeoutMs": options.get(
                                    "teardownTimeoutMs"
                                ),
                                "onStepStart": options.get("onStepStart"),
                                "onStepResult": options.get("onStepResult"),
                                "onResult": make_on_result(attempt_index),
                                "reportScopeId": (
                                    resolve_scope(
                                        collected_case,
                                        attempt_index,
                                        started_document["documentRunId"],
                                    )
                                    if resolve_scope
                                    else None
                                ),
                                "createRunId": (
                                    (
                                        lambda: create_case_run_id(
                                            collected_case, attempt_index
                                        )
                                    )
                                    if create_case_run_id
                                    else None
                                ),
                            },
                        )
                    except WorkflowExecutionFailure as error:
                        attempt_failure = error
                        run = error.result

                    attempts.append(run)
                    if attempt_failure is not None and not all(
                        is_resource_recovery_error(error)
                        for error in attempt_failure.errors
                    ):
                        run["retryDecision"] = decide_retry(
                            {
                                "scope": "case",
                                "retryCount": retry,
                                "attemptIndex": attempt_index,
                                "status": run.get("status"),
                                "infrastructureError": True,
                            }
                        )
                        cases.append(
                            _case_outcome(
                                collected_case,
                                project_name,
                                "failed",
                                run,
                                attempts,
                            )
                        )
                        raise attempt_failure

                    fatal_error = attempt_fatal_error
                    cleanup = run.get("cleanup") or {}
                    run["retryDecision"] = decide_retry(
                        {
                            "scope": "case",
                            "retryCount": retry,
                            "attemptIndex": attempt_index,
                            "status": run.get("status"),
                            "cleanupPending": cleanup.get("status")
                            == "pending",
                            "cleanupFailed": cleanup.get("status") == "failed"
                            or bool(run.get("teardownErrors")),
                            "operationPending": bool(
                                run.get("pendingOperations")
                            ),
                            "fatalError": fatal_error
                            or any(
                                is_resource_recovery_error(error)
                                for error in run.get("executionErrors") or []
                            ),
                            "interrupted": signal.aborted,
                            "shouldStop": (
                                options.get("shouldStop")()
                                if options.get("shouldStop")
                                else False
                            ),
                        }
                    )
                    if (run.get("retryDecision") or {}).get("decision") != "retry":
                        break

                run = attempts[-1]
                outcome = _case_outcome(
                    collected_case,
                    project_name,
                    run.get("status"),
                    run,
                    attempts,
                )
                cases.append(outcome)
                retry_stop_reason = (run.get("retryDecision") or {}).get(
                    "reason"
                )
                if retry_stop_reason in (
                    "cleanup-pending",
                    "cleanup-failed",
                    "operation-pending",
                    "fatal-error",
                ):
                    document_stop_reason = retry_stop_reason
                elif (
                    outcome.get("status") == "failed"
                    and collected_case["definition"].get("onFailure")
                    == "stop-document"
                ):
                    document_stop_reason = "bail"
                else:
                    document_stop_reason = None
                await _call(options.get("onCaseOutcome"), outcome)
    except Exception as error:
        if isinstance(error, WorkflowExecutionFailure):
            execution_errors.extend(error.errors)
        else:
            execution_errors.append(error)
    finally:
        if runtime_started:
            try:
                document_result = await runtime.finish()
            except WorkflowExecutionFailure as error:
                document_result = error.result
                for failure in error.errors:
                    if not any(item is failure for item in execution_errors):
                        execution_errors.append(failure)
            except Exception as error:
                execution_errors.append(error)

    if document_result is None:
        if execution_errors:
            raise WorkflowAggregateError(
                execution_errors,
                "Workflow execution did not produce a document result.",
            )
        raise RuntimeError(
            f'Workflow document "{document.get("sourcePath")}" did not produce a result.'
        )
    if execution_errors:
        completed = {outcome.get("caseId") for outcome in cases}
        all_resource_recovery = all(
            is_resource_recovery_error(error) for error in execution_errors
        )
        for item in document["cases"]:
            if item["caseId"] not in completed:
                cases.append(
                    _as_not_run(
                        item,
                        project_name,
                        "operation-pending"
                        if all_resource_recovery
                        else "interrupted",
                    )
                )
        document_result["status"] = "failed"
        document_result["executionErrors"] = [
            as_execution_error(error)
            for error in execution_errors
            if not any(
                host.get("error") is error
                for host in document_result.get("hostErrors") or []
            )
        ]
        raise WorkflowExecutionFailure(
            {"document": document_result, "cases": cases},
            execution_errors,
        )
    return {"document": document_result, "cases": cases}


__all__ = ["run_workflow_document"]
