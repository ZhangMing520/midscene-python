"""Test-run report dump builder (upstream reporting/test-run-report.ts)."""

import datetime
from dataclasses import dataclass, field
from typing import Any, Literal, cast, overload

from midscene.core.test_run_report import (
    IndexedTestRunReportSource,
    TestRunReportAgentDetail,
    TestRunReportAttempt,
    TestRunReportCase,
    TestRunReportCasePlan,
    TestRunReportDiagnostic,
    TestRunReportDocument,
    TestRunReportDocumentPlan,
    TestRunReportDump,
    TestRunReportMetrics,
    TestRunReportPlannedStep,
    TestRunReportProject,
    TestRunReportProjectLifecycle,
    TestRunReportSource,
    TestRunReportSourceIndex,
    TestRunReportStep,
)
from midscene.core.test_runner.reporting.metrics import (
    sum_test_run_report_metrics,
)
from midscene.core.test_runner.reporting.sanitize import (
    sanitize_report_error,
    sanitize_report_text,
    sanitize_report_value,
)
from midscene.core.test_runner.reporting.types import (
    RunReportCaseInput,
    RunReportInput,
    RunReportProjectInput,
)

_EXACT_MIDSCENE_DETAIL_NODES = {"aiAct", "aiAssert", "recordToReport"}
_CasePlanKey = Literal["beforeEach", "steps", "afterEach"]
_DocumentPlanKey = Literal["beforeAll", "afterAll"]


@dataclass
class _ManifestBuildContext:
    diagnostics: list[TestRunReportDiagnostic] = field(default_factory=list)
    sources_by_scope: dict[str, list[IndexedTestRunReportSource]] = field(
        default_factory=dict
    )
    details_by_scope_and_execution: dict[str, TestRunReportAgentDetail] = field(
        default_factory=dict
    )
    traced_scope_by_execution: dict[str, str] = field(default_factory=dict)
    expected_executions: set[str] = field(default_factory=set)
    captured_executions: set[str] = field(default_factory=set)
    execution_metrics: dict[str, TestRunReportMetrics] = field(default_factory=dict)
    missing_metrics: set[str] = field(default_factory=set)
    traced_scopes: set[str] = field(default_factory=set)


def _scoped_execution_key(scope_id: Any, execution_id: Any) -> str:
    return f"{scope_id}\u0000{execution_id}"


def _report_sources_for_scope(
    context: _ManifestBuildContext, scope_id: Any
) -> list[IndexedTestRunReportSource]:
    return context.sources_by_scope.get(scope_id) or []


def _add_diagnostic(
    context: _ManifestBuildContext, diagnostic: TestRunReportDiagnostic
) -> None:
    context.diagnostics.append(diagnostic)


def _attempts(outcome: RunReportCaseInput) -> list[Any]:
    attempts = outcome.get("attempts")
    if attempts is not None:
        return list(attempts)
    run = outcome.get("run")
    return [run] if run else []


@overload
def _planned_step(
    plan: TestRunReportCasePlan | None, key: _CasePlanKey, index: Any
) -> TestRunReportPlannedStep | None: ...


@overload
def _planned_step(
    plan: TestRunReportDocumentPlan | None, key: _DocumentPlanKey, index: Any
) -> TestRunReportPlannedStep | None: ...


def _planned_step(
    plan: TestRunReportCasePlan | TestRunReportDocumentPlan | None,
    key: _CasePlanKey | _DocumentPlanKey,
    index: Any,
) -> TestRunReportPlannedStep | None:
    if plan is None:
        return None
    steps = cast(list[TestRunReportPlannedStep], plan.get(key) or [])
    if isinstance(index, int) and 0 <= index < len(steps):
        return steps[index]
    return None


def _copy_operations(operations: Any) -> dict[str, Any]:
    return {**operations, "events": list(operations.get("events") or [])}


def _build_step(
    step: Any,
    scope_id: Any,
    context: _ManifestBuildContext,
    execution_id: str,
    plan: TestRunReportPlannedStep | None = None,
) -> TestRunReportStep:
    step_id = f"{execution_id}:{step.get('phase')}:{step.get('stepIndex')}"
    if step.get("status") == "not-run":
        result: TestRunReportStep = {"id": step_id}
        if plan is not None:
            result["planStepId"] = cast(str, plan.get("id"))
            if plan.get("title"):
                result["title"] = plan["title"]
        result["phase"] = step.get("phase")
        result["stepIndex"] = step.get("stepIndex")
        result["node"] = step.get("node")
        result["status"] = "not-run"
        result["notRunReason"] = sanitize_report_text(step.get("notRunReason") or "")
        if step.get("blockedBy"):
            result["blockedBy"] = step["blockedBy"]
        result["continuedAfterError"] = bool(step.get("continuedAfterError"))
        if step.get("waitForPreviousOperationMs"):
            result["waitForPreviousOperationMs"] = step["waitForPreviousOperationMs"]
        result["input"] = sanitize_report_value(step.get("input"))
        if step.get("error") is not None:
            result["error"] = sanitize_report_error(step["error"])
        if step.get("operations"):
            result["operations"] = _copy_operations(step["operations"])
        return result

    details: list[TestRunReportAgentDetail] = []
    unresolved_execution_ids: list[str] = []
    usage: list[TestRunReportMetrics] = []
    missing_usage: list[str] = []
    report = step.get("report") or {}
    for trace in report.get("traces") or []:
        context.traced_scopes.add(scope_id)
        trace_execution_id = cast(str, trace.get("executionId"))
        metrics = context.execution_metrics.get(trace_execution_id)
        if metrics is None:
            metrics = trace.get("metrics")
        if metrics:
            context.execution_metrics[trace_execution_id] = metrics
            usage.append(metrics)
        key = _scoped_execution_key(scope_id, trace_execution_id)
        context.expected_executions.add(key)
        previous_scope = context.traced_scope_by_execution.get(trace_execution_id)
        if previous_scope and previous_scope != scope_id:
            raise ValueError(
                f"Agent execution {trace_execution_id} was traced by multiple test "
                f"scopes ({previous_scope}, {scope_id})."
            )
        context.traced_scope_by_execution[trace_execution_id] = scope_id
        detail = context.details_by_scope_and_execution.get(key)
        if detail:
            details.append(detail)
            context.captured_executions.add(key)
        else:
            unresolved_execution_ids.append(trace_execution_id)
            if not metrics:
                reason = (
                    f"Model usage is unavailable for execution {trace_execution_id}."
                )
                missing_usage.append(reason)
                context.missing_metrics.add(reason)

    agent_detail_diagnostic: str | None = None
    if unresolved_execution_ids:
        agent_detail_diagnostic = (
            "Agent detail could not be resolved for "
            f"{', '.join(unresolved_execution_ids)}."
        )
        sources = _report_sources_for_scope(context, scope_id)
        for unresolved_id in unresolved_execution_ids:
            diagnostic: TestRunReportDiagnostic = {
                "level": "warning",
                "code": "agent-detail-unresolved",
                "message": (
                    f"Agent detail could not be resolved for execution "
                    f"{unresolved_id} in test scope {scope_id}."
                ),
                "scopeId": scope_id,
                "executionId": unresolved_id,
                "stepId": step_id,
            }
            if sources:
                diagnostic["sourcePaths"] = [
                    cast(str, source.get("sourcePath")) for source in sources
                ]
            _add_diagnostic(context, diagnostic)
    elif not details and step.get("node") in _EXACT_MIDSCENE_DETAIL_NODES:
        agent_detail_diagnostic = (
            "This Agent did not expose a stable execution reference for the Step."
        )
        diagnostic = {
            "level": "warning",
            "code": "agent-detail-unavailable",
            "message": (
                f"No stable Agent execution reference was captured for "
                f"{step.get('node')} in test scope {scope_id}."
            ),
            "scopeId": scope_id,
            "stepId": step_id,
        }
        sources = _report_sources_for_scope(context, scope_id)
        if sources:
            diagnostic["sourcePaths"] = [
                cast(str, source.get("sourcePath")) for source in sources
            ]
        _add_diagnostic(context, diagnostic)

    collection_errors = [
        sanitize_report_error(error) for error in (report.get("collectionErrors") or [])
    ]
    for error in collection_errors:
        _add_diagnostic(
            context,
            {
                "level": "warning",
                "code": "agent-source-unavailable",
                "scopeId": scope_id,
                "stepId": step_id,
                "error": error,
                "message": f"Report collection for {step.get('node')}: {error.get('message')}",
            },
        )
    snapshots = [
        source["collection"]
        for source in (report.get("sources") or [])
        if source.get("collection")
    ]
    evidence_collection: dict[str, Any] | None = None
    if snapshots or collection_errors or details or unresolved_execution_ids:
        if (
            collection_errors
            or unresolved_execution_ids
            or any(snapshot.get("status") == "partial" for snapshot in snapshots)
        ):
            status = "partial" if details else "unknown"
        else:
            status = "complete"
        evidence_collection = {"status": status}
        if snapshots:
            captured_times = sorted(
                snapshot.get("capturedAt") for snapshot in snapshots
            )
            evidence_collection["capturedAt"] = captured_times[-1]
        if collection_errors:
            evidence_collection["errors"] = collection_errors

    # A missing link does not invalidate usage already captured independently.
    if not (report.get("traces") or []) and collection_errors and not details:
        reason = f"Model usage could not be collected for step {step_id}."
        missing_usage.append(reason)
        context.missing_metrics.add(reason)

    input_value = step.get("input")
    candidate_title = None
    if isinstance(input_value, dict):
        candidate_title = (
            input_value.get("prompt")
            or input_value.get("script")
            or input_value.get("scenario")
            or input_value.get("title")
        )
    prompt: str | None = None
    if isinstance(candidate_title, str):
        prompt = candidate_title
    elif isinstance(candidate_title, dict):
        nested_prompt = candidate_title.get("prompt")
        if isinstance(nested_prompt, str):
            prompt = nested_prompt

    result = {"id": step_id}
    if plan is not None:
        result["planStepId"] = cast(str, plan.get("id"))
    result["phase"] = step.get("phase")
    result["stepIndex"] = step.get("stepIndex")
    result["node"] = step.get("node")
    if prompt:
        result["title"] = sanitize_report_text(prompt, 240)
    result["status"] = step.get("status")
    result["continuedAfterError"] = bool(step.get("continuedAfterError"))
    if step.get("waitForPreviousOperationMs"):
        result["waitForPreviousOperationMs"] = step["waitForPreviousOperationMs"]
    result["startedAt"] = step.get("startedAt")
    result["endedAt"] = step.get("endedAt")
    result["durationMs"] = step.get("durationMs")
    if step.get("operations"):
        result["operations"] = _copy_operations(step["operations"])
    result["input"] = sanitize_report_value(step.get("input"))
    if step.get("output") is not None:
        output = step["output"]
        sanitized_output: dict[str, Any] = {}
        if output.get("summary") is not None:
            sanitized_output["summary"] = sanitize_report_text(output["summary"])
        if output.get("data") is not None:
            sanitized_output["data"] = sanitize_report_value(output["data"])
        result["output"] = sanitized_output
    if step.get("error") is not None:
        result["error"] = sanitize_report_error(step["error"])
    if details:
        result["agentDetails"] = details
    if agent_detail_diagnostic:
        result["agentDetailDiagnostic"] = agent_detail_diagnostic
    if usage or missing_usage:
        result["metrics"] = sum_test_run_report_metrics(usage, missing_usage)
    if evidence_collection is not None:
        result["evidenceCollection"] = {
            **evidence_collection,
            **({"modelUsageUnavailable": True} if missing_usage else {}),
        }
    return result


def _attempt_report_scope(attempt: Any) -> str:
    return cast(str, attempt.get("reportScopeId") or attempt.get("runId"))


def _build_attempt(
    attempt: Any,
    context: _ManifestBuildContext,
    plan: TestRunReportCasePlan | None = None,
) -> TestRunReportAttempt:
    scope_id = _attempt_report_scope(attempt)
    result: TestRunReportAttempt = {
        "attemptId": attempt.get("runId"),
        "attemptIndex": attempt.get("attemptIndex"),
        "status": attempt.get("status"),
    }
    if attempt.get("executionStatus"):
        result["executionStatus"] = attempt["executionStatus"]
    if attempt.get("phases") is not None:
        result["phases"] = attempt["phases"]
    if attempt.get("cleanup") is not None:
        result["cleanup"] = attempt["cleanup"]
    if attempt.get("pendingOperations") is not None:
        result["pendingOperations"] = attempt["pendingOperations"]
    if attempt.get("retryDecision") is not None:
        result["retryDecision"] = attempt["retryDecision"]
    result["startedAt"] = attempt.get("startedAt")
    result["endedAt"] = attempt.get("endedAt")
    result["durationMs"] = attempt.get("durationMs")
    result["beforeEach"] = [
        _build_step(
            step,
            scope_id,
            context,
            attempt.get("runId"),
            _planned_step(plan, "beforeEach", step.get("stepIndex")),
        )
        for step in (attempt.get("beforeEach") or [])
    ]
    result["steps"] = [
        _build_step(
            step,
            scope_id,
            context,
            attempt.get("runId"),
            _planned_step(plan, "steps", step.get("stepIndex")),
        )
        for step in (attempt.get("steps") or [])
    ]
    result["afterEach"] = [
        _build_step(
            step,
            scope_id,
            context,
            attempt.get("runId"),
            _planned_step(plan, "afterEach", step.get("stepIndex")),
        )
        for step in (attempt.get("afterEach") or [])
    ]
    execution_errors = attempt.get("executionErrors") or []
    if execution_errors:
        result["hostErrors"] = [
            {"phase": "execution", "error": sanitize_report_error(error)}
            for error in execution_errors
        ]
    teardown_errors = attempt.get("teardownErrors") or []
    if teardown_errors:
        result["teardownErrors"] = [
            sanitize_report_error(error) for error in teardown_errors
        ]
    sources = _report_sources_for_scope(context, scope_id)
    if sources:
        result["scopeReportIds"] = [
            cast(str, source.get("reportId")) for source in sources
        ]
    return result


def _build_case(
    outcome: RunReportCaseInput,
    context: _ManifestBuildContext,
    plan: TestRunReportCasePlan | None = None,
) -> TestRunReportCase:
    result: TestRunReportCase = {}
    if plan is not None:
        result["plan"] = plan
    result["caseId"] = cast(str, outcome.get("caseId"))
    result["name"] = cast(str, outcome.get("name"))
    result["caseIndex"] = cast(int, outcome.get("caseIndex"))
    result["status"] = cast(str, outcome.get("status"))
    if outcome.get("notRunReason"):
        result["notRunReason"] = outcome["notRunReason"]
    result["attempts"] = [
        _build_attempt(attempt, context, plan) for attempt in _attempts(outcome)
    ]
    return result


def _document_report_scope(document: Any) -> str:
    return cast(str, document.get("reportScopeId") or document.get("documentRunId"))


def _find_plan(plans: Any, document_id: Any) -> TestRunReportDocumentPlan | None:
    for plan in plans or []:
        if plan.get("documentId") == document_id:
            return cast(TestRunReportDocumentPlan, plan)
    return None


def _build_document(
    document_id: str,
    document: Any | None,
    cases: list[RunReportCaseInput],
    context: _ManifestBuildContext,
    plan: TestRunReportDocumentPlan | None = None,
) -> TestRunReportDocument:
    if plan is None and document is not None:
        plan = document.get("plan")
    source_path = None
    if document is not None:
        source_path = document.get("sourcePath")
    if not source_path and cases:
        source_path = cases[0].get("sourcePath")
    if not source_path:
        source_path = "<unknown>"
    if document is not None:
        status = document.get("status")
    else:
        status = (
            "failed"
            if any(case.get("status") != "success" for case in cases)
            else "success"
        )
    if status is None:
        status = (
            "failed"
            if any(case.get("status") != "success" for case in cases)
            else "success"
        )
    scope_id = _document_report_scope(document) if document is not None else None

    result: TestRunReportDocument = {"documentId": document_id}
    if plan is not None:
        result["plan"] = plan
    if document is not None:
        result["logicalDocumentId"] = document.get("documentId")
        result["documentRunId"] = document.get("documentRunId")
        if document.get("attemptIndex") is not None:
            result["attemptIndex"] = document["attemptIndex"]
    result["sourcePath"] = source_path
    result["status"] = status
    if document is not None:
        if document.get("executionStatus"):
            result["executionStatus"] = document["executionStatus"]
        if document.get("phases") is not None:
            result["phases"] = document["phases"]
        if document.get("cleanup") is not None:
            result["cleanup"] = document["cleanup"]
        if document.get("pendingOperations") is not None:
            result["pendingOperations"] = document["pendingOperations"]
        if document.get("retryDecision") is not None:
            result["retryDecision"] = document["retryDecision"]
        result["startedAt"] = document.get("startedAt")
        result["endedAt"] = document.get("endedAt")
        result["durationMs"] = document.get("durationMs")
    document_steps = document if document is not None else {}
    document_run_id = cast(
        str, document.get("documentRunId") if document is not None else None
    )
    result["beforeAll"] = [
        _build_step(
            step,
            scope_id,
            context,
            document_run_id,
            _planned_step(plan, "beforeAll", step.get("stepIndex")),
        )
        for step in (document_steps.get("beforeAll") or [])
    ]
    result["cases"] = [
        _build_case(
            outcome,
            context,
            next(
                (
                    item
                    for item in ((plan.get("cases") or []) if plan else [])
                    if item.get("caseId") == outcome.get("caseId")
                ),
                None,
            )
            if plan is not None
            else None,
        )
        for outcome in cases
    ]
    result["afterAll"] = [
        _build_step(
            step,
            scope_id,
            context,
            document_run_id,
            _planned_step(plan, "afterAll", step.get("stepIndex")),
        )
        for step in (document_steps.get("afterAll") or [])
    ]
    host_errors = document_steps.get("hostErrors") or []
    execution_errors = document_steps.get("executionErrors") or []
    if host_errors or execution_errors:
        combined = list(host_errors) + [
            {"phase": "execution", "error": error} for error in execution_errors
        ]
        result["hostErrors"] = [
            {
                "phase": item.get("phase"),
                "error": sanitize_report_error(item.get("error")),
            }
            for item in combined
        ]
    teardown_errors = document_steps.get("teardownErrors") or []
    if teardown_errors:
        result["teardownErrors"] = [
            sanitize_report_error(error) for error in teardown_errors
        ]
    if scope_id:
        sources = _report_sources_for_scope(context, scope_id)
        if sources:
            result["scopeReportIds"] = [
                cast(str, source.get("reportId")) for source in sources
            ]
    return result


def _parse_ms(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return (
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            * 1000
        )
    except ValueError:
        return None


def _build_project(
    project: RunReportProjectInput,
    context: _ManifestBuildContext,
) -> TestRunReportProject:
    documents_input = project.get("documents") or []
    cases_input = project.get("cases") or []
    plans = project.get("plans")

    document_count: dict[str, int] = {}
    for document in documents_input:
        document_id = cast(str, document.get("documentId"))
        document_count[document_id] = document_count.get(document_id, 0) + 1
    for outcome in cases_input:
        if document_count.get(
            cast(str, outcome.get("documentId")), 0
        ) > 1 and not outcome.get("documentRunId"):
            raise ValueError(
                f"Case {outcome.get('caseId')} must identify its documentRunId "
                "when a document has multiple attempts."
            )

    # A new attemptIndex 0 begins a distinct invocation of the same file. Only
    # whole-file retries belong to one logical document and its Case history.
    groups: list[list[Any]] = []
    current_group: dict[str, list[Any]] = {}
    for document in documents_input:
        document_id = cast(str, document.get("documentId"))
        group = current_group.get(document_id)
        if group is None or not document.get("attemptIndex"):
            group = []
            groups.append(group)
            current_group[document_id] = group
        group.append(document)

    group_counts: dict[str, int] = {}
    for group in groups:
        first_id = cast(str, group[0].get("documentId"))
        group_counts[first_id] = group_counts.get(first_id, 0) + 1

    documents: list[TestRunReportDocument] = []
    for group in groups:
        first = group[0]
        last = group[-1]
        first_document_id = cast(str, first.get("documentId"))
        document_id = cast(
            str,
            f"{first.get('documentId')}:{first.get('documentRunId')}"
            if group_counts.get(first_document_id, 0) > 1
            else first.get("documentId"),
        )
        outcomes: dict[str, RunReportCaseInput] = {}
        for document in group:
            for outcome in cases_input:
                if outcome.get("documentId") != document.get("documentId"):
                    continue
                if outcome.get("documentRunId") and outcome.get(
                    "documentRunId"
                ) != document.get("documentRunId"):
                    continue
                case_id = cast(str, outcome.get("caseId"))
                previous = outcomes.get(case_id)
                previous_attempts = (previous.get("attempts") or []) if previous else []
                document_attempt_index = document.get("attemptIndex")
                merged = []
                for attempt in _attempts(outcome):
                    attempt_index = (
                        document_attempt_index
                        if document_attempt_index is not None
                        else attempt.get("attemptIndex")
                    )
                    merged.append({**attempt, "attemptIndex": attempt_index})
                outcomes[case_id] = {
                    **outcome,
                    "attempts": previous_attempts + merged,
                }
        result = _build_document(
            document_id,
            last,
            list(outcomes.values()),
            context,
            _find_plan(plans, last.get("documentId")),
        )
        if len(group) > 1:
            result["startedAt"] = first.get("startedAt")
            end_ms = _parse_ms(last.get("endedAt"))
            start_ms = _parse_ms(first.get("startedAt"))
            result["durationMs"] = (
                max(0.0, end_ms - start_ms)
                if end_ms is not None and start_ms is not None
                else 0.0
            )
            attempt_documents: list[dict[str, Any]] = []
            for document in group:
                attempt = dict(
                    _build_document(
                        document_id,
                        document,
                        [],
                        context,
                        _find_plan(plans, document.get("documentId")),
                    )
                )
                attempt.pop("cases", None)
                attempt_documents.append(attempt)
            result["attempts"] = attempt_documents
        documents.append(result)

    # Collection/setup failures can have Cases but no started document runtime.
    for document_id in dict.fromkeys(
        cast(str, outcome.get("documentId")) for outcome in cases_input
    ):
        if document_id not in document_count:
            documents.append(
                _build_document(
                    document_id,
                    None,
                    [
                        outcome
                        for outcome in cases_input
                        if outcome.get("documentId") == document_id
                    ],
                    context,
                    _find_plan(plans, document_id),
                )
            )

    project_result: TestRunReportProject = {}
    if plans is not None:
        project_result["plans"] = plans
    project_result["projectId"] = cast(str, project.get("projectId"))
    if project.get("name") is not None:
        project_result["name"] = cast(str, project.get("name"))
    platform = project.get("platform")
    if isinstance(platform, str) and platform.strip():
        project_result["platform"] = platform.strip()
    project_result["status"] = cast(str, project.get("status"))
    project_result["retry"] = cast(int, project.get("retry"))
    lifecycle = project.get("lifecycle")
    if lifecycle is not None:
        project_lifecycle: TestRunReportProjectLifecycle = {
            "status": lifecycle.get("status"),
            "startedAt": lifecycle.get("startedAt"),
            "endedAt": lifecycle.get("endedAt"),
            "durationMs": lifecycle.get("durationMs"),
        }
        if lifecycle.get("cleanup") is not None:
            project_lifecycle["cleanup"] = lifecycle["cleanup"]
        if lifecycle.get("pendingOperations") is not None:
            project_lifecycle["pendingOperations"] = lifecycle["pendingOperations"]
        if lifecycle.get("setupError") is not None:
            project_lifecycle["setupError"] = sanitize_report_error(
                lifecycle["setupError"]
            )
        teardown_errors = lifecycle.get("teardownErrors") or []
        if teardown_errors:
            project_lifecycle["teardownErrors"] = [
                sanitize_report_error(error) for error in teardown_errors
            ]
        project_result["lifecycle"] = project_lifecycle
    project_result["documents"] = documents
    project_result["collectionErrors"] = [
        {
            "sourcePath": cast(str, collection_error.get("sourcePath")),
            "error": sanitize_report_error(collection_error.get("error")),
        }
        for collection_error in (project.get("collectionErrors") or [])
    ]
    return project_result


def collect_test_run_report_sources(
    result: RunReportInput,
) -> list[TestRunReportSource]:
    """Report sources reachable from the projected execution records."""
    sources: list[TestRunReportSource] = []
    for project in result.get("projects") or []:
        for document in project.get("documents") or []:
            scope_id = _document_report_scope(document)
            document_sources = document.get("reportSources") or []
            for source in document_sources:
                sources.append({**source, "scopeId": scope_id})
            for source_path in document.get("reportPaths") or []:
                if any(
                    source.get("sourcePath") == source_path
                    for source in document_sources
                ):
                    continue
                sources.append({"scopeId": scope_id, "sourcePath": source_path})
        for outcome in project.get("cases") or []:
            for attempt in _attempts(outcome):
                scope_id = _attempt_report_scope(attempt)
                attempt_sources = attempt.get("reportSources") or []
                for source in attempt_sources:
                    sources.append({**source, "scopeId": scope_id})
                for source_path in attempt.get("reportPaths") or []:
                    if any(
                        source.get("sourcePath") == source_path
                        for source in attempt_sources
                    ):
                        continue
                    sources.append({"scopeId": scope_id, "sourcePath": source_path})
    return sources


def build_test_run_report_dump(
    result: RunReportInput,
    index: TestRunReportSourceIndex,
) -> TestRunReportDump:
    sources_by_scope: dict[str, list[IndexedTestRunReportSource]] = {}
    details_by_scope_and_execution: dict[str, TestRunReportAgentDetail] = {}
    for source in index.get("sources") or []:
        scope_id = cast(str, source.get("scopeId"))
        scope_sources = sources_by_scope.setdefault(scope_id, [])
        scope_sources.append(source)
        for execution_id in source.get("executionIds") or []:
            details_by_scope_and_execution[
                _scoped_execution_key(scope_id, execution_id)
            ] = {
                "reportId": cast(str, source.get("reportId")),
                "executionId": execution_id,
            }

    context = _ManifestBuildContext(
        diagnostics=[
            {
                **diagnostic,
                "message": sanitize_report_text(diagnostic.get("message") or ""),
            }
            for diagnostic in (index.get("diagnostics") or [])
        ],
        sources_by_scope=sources_by_scope,
        details_by_scope_and_execution=details_by_scope_and_execution,
        execution_metrics=dict(index.get("executionMetrics") or {}),
    )

    for error in result.get("errors") or []:
        sanitized_error = sanitize_report_error(error)
        _add_diagnostic(
            context,
            {
                "level": "error",
                "code": "run-infrastructure-error",
                "message": cast(str, sanitized_error.get("message")),
                "error": sanitized_error,
            },
        )
    for source in index.get("sources") or []:
        if not (source.get("executionIds") or []):
            _add_diagnostic(
                context,
                {
                    "level": "warning",
                    "code": "source-without-executions",
                    "message": (
                        "Agent report contains no executions: "
                        f"{source.get('sourcePath')}"
                    ),
                    "scopeId": cast(str, source.get("scopeId")),
                    "sourcePaths": [cast(str, source.get("sourcePath"))],
                },
            )

    projects = [
        _build_project(project, context) for project in (result.get("projects") or [])
    ]
    for diagnostic in index.get("diagnostics") or []:
        if diagnostic.get("code") == "agent-source-unavailable" and (
            not diagnostic.get("scopeId")
            or diagnostic.get("scopeId") not in context.traced_scopes
        ):
            context.missing_metrics.add(cast(str, diagnostic.get("message")))

    index_execution_metrics = index.get("executionMetrics")
    index_metrics = index.get("metrics") or {}
    metric_values: list[TestRunReportMetrics] = []
    if (index.get("sources") or []) or (
        index_execution_metrics is None
        and (index_metrics.get("modelCallCount") or index_metrics.get("collection"))
    ):
        metric_values.append(index.get("capturedMetrics") or index_metrics)
    for execution_id, value in context.execution_metrics.items():
        if not (index_execution_metrics or {}).get(execution_id):
            metric_values.append(value)
    metrics = sum_test_run_report_metrics(metric_values, list(context.missing_metrics))

    dump: TestRunReportDump = {
        "schemaVersion": 1,
        "kind": "test-runner",
        "runId": cast(str, result.get("runId")),
    }
    operation_log = result.get("operationLog")
    if operation_log is not None:
        dump["operationLogs"] = [{**operation_log}]
    dump["status"] = cast(str, result.get("status"))
    dump["startedAt"] = cast(str, result.get("startedAt"))
    dump["endedAt"] = cast(str, result.get("endedAt"))
    dump["durationMs"] = cast(float, result.get("durationMs"))
    dump["summary"] = {**(result.get("summary") or {})}
    dump["metrics"] = {
        **metrics,
        "collection": {
            **(metrics.get("collection") or {}),
            "expectedExecutionCount": len(context.expected_executions),
            "capturedExecutionCount": len(context.captured_executions),
        },
    }
    if index_execution_metrics is not None or context.execution_metrics:
        dump["executionMetrics"] = dict(context.execution_metrics)
    dump["projects"] = projects
    if context.diagnostics:
        dump["diagnostics"] = context.diagnostics
    return dump


__all__ = ["build_test_run_report_dump", "collect_test_run_report_sources"]
