"""Merge multiple report dumps (upstream reporting/merge-report.ts)."""

import datetime
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypedDict, cast

from midscene.core.test_run_report import (
    TestRunReportDiagnostic,
    TestRunReportDocument,
    TestRunReportDump,
    TestRunReportMetrics,
    TestRunReportProject,
    TestRunReportSummary,
)
from midscene.core.test_runner.reporting.metrics import (
    sum_test_run_report_metrics,
)


class MergeTestRunReportSource(TypedDict, total=False):
    reportId: str
    sourcePath: str
    attributes: dict[str, Any]
    dump: TestRunReportDump | None
    timing: dict[str, Any] | None


_REFERENCE_KEYS = (
    "blockedByStepId",
    "stepId",
    "scopeId",
    "caseId",
    "runId",
    "documentId",
    "documentRunId",
)

_FRAMEWORK_DETAIL_CODES = {
    "RESOURCE_RECOVERY_TIMEOUT",
    "RESOURCE_CLEANUP_DEFERRED",
    "NODE_SCOPE_TEARDOWN_ERROR",
    "REPORT_SNAPSHOT_FAILED",
    "CASE_EXECUTION_FAILED",
    "WORKFLOW_DOCUMENT_EXECUTION_FAILED",
}

_SummaryKey = Literal[
    "total",
    "passed",
    "failed",
    "notRun",
    "filtered",
    "collectionErrors",
    "documentFailures",
    "projectFailures",
]
_SUMMARY_KEYS: tuple[_SummaryKey, ...] = (
    "total",
    "passed",
    "failed",
    "notRun",
    "filtered",
    "collectionErrors",
    "documentFailures",
    "projectFailures",
)

_METRIC_FIELDS = (
    "modelCallCount",
    "modelTimeMs",
    "totalTokens",
    "promptTokens",
    "completionTokens",
)


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


def _iso_ms(value: float) -> str:
    return (
        datetime.datetime.fromtimestamp(value / 1000, tz=datetime.UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _remap_error(error: Any, id_for: Callable[[str], str]) -> dict[str, Any]:
    def remap_references(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for key in _REFERENCE_KEYS:
            if isinstance(result.get(key), str):
                result[key] = id_for(result[key])
        return result

    details = error.get("details")
    # Only framework-owned details contain report links. Do not rewrite matching
    # property names in custom errors or arbitrary nested business data.
    if details and error.get("code") in _FRAMEWORK_DETAIL_CODES:
        value = remap_references(details.get("value"))
        if isinstance(value, dict):
            for key in ("blockingOperations", "diagnostics"):
                if isinstance(value.get(key), list):
                    value[key] = [remap_references(item) for item in value[key]]
        details = {**details, "value": value}
    result = {**error}
    if details:
        result["details"] = details
    if error.get("cause") is not None:
        result["cause"] = _remap_error(error["cause"], id_for)
    if error.get("errors") is not None:
        result["errors"] = [_remap_error(item, id_for) for item in error["errors"]]
    return result


def _agent_report_as_test_run(
    source: MergeTestRunReportSource,
) -> dict[str, Any]:
    attributes = source.get("attributes") or {}
    report_id = source.get("reportId")
    test_status = attributes.get("testStatus")
    if test_status == "skipped":
        status = "not-run"
    elif test_status == "passed":
        status = "success"
    else:
        status = "failed"
    failed = status == "failed"
    timing = source.get("timing")
    result: dict[str, Any] = {
        "status": "failed" if failed else "success",
        "summary": {
            "total": 1,
            "passed": 1 if status == "success" else 0,
            "failed": 1 if failed else 0,
            "notRun": 1 if status == "not-run" else 0,
            "filtered": 0,
            "collectionErrors": 0,
            "documentFailures": 0,
            "projectFailures": 0,
        },
        "projects": [
            {
                "projectId": "agent-report",
                "name": attributes.get("testTitle"),
                "platform": "agent",
                "status": "failed" if failed else "success",
                "retry": 0,
                "collectionErrors": [],
                "documents": [
                    {
                        "documentId": "agent-report",
                        "sourcePath": source.get("sourcePath"),
                        "status": "failed" if failed else "success",
                        "beforeAll": [],
                        "afterAll": [],
                        "scopeReportIds": [report_id],
                        "cases": [
                            {
                                "caseId": attributes.get("testId"),
                                "name": attributes.get("testTitle"),
                                "caseIndex": 0,
                                "status": status,
                                "attempts": (
                                    []
                                    if status == "not-run" or timing is None
                                    else [
                                        {
                                            "attemptId": "agent-report",
                                            "attemptIndex": 0,
                                            "status": status,
                                            **timing,
                                            "beforeEach": [],
                                            "steps": [],
                                            "afterEach": [],
                                            "scopeReportIds": [report_id],
                                        }
                                    ]
                                ),
                            }
                        ],
                    }
                ],
            }
        ],
    }
    if timing is not None:
        for key, value in timing.items():
            result[key] = value
    return result


def _retain_host_failure(
    source: MergeTestRunReportSource,
) -> TestRunReportDump | None:
    dump = source.get("dump")
    attributes = source.get("attributes") or {}
    if (
        dump is None
        or dump.get("status") == "failed"
        or attributes.get("testStatus") not in ("failed", "timedOut", "interrupted")
    ):
        return dump

    message = (
        f'Host test "{attributes.get("testTitle")}" finished with status '
        f'"{attributes.get("testStatus")}".'
    )
    projects = dump.get("projects") or []
    project_index = len(projects) - 1
    project = projects[project_index] if project_index >= 0 else None
    documents = (project or {}).get("documents") or []
    document_index = len(documents) - 1
    document = documents[document_index] if document_index >= 0 else None

    def after_host(value: Mapping[str, Any]) -> dict[str, Any]:
        ended_at = value.get("endedAt") or dump.get("endedAt")
        after_all = list(value.get("afterAll") or [])
        after_all.append(
            {
                "id": (
                    f"{value.get('documentRunId') or value.get('documentId')}"
                    ":host-result"
                ),
                "phase": "afterAll",
                "stepIndex": len(after_all),
                "node": "runner:host-result",
                "status": "failed",
                "continuedAfterError": False,
                "startedAt": ended_at,
                "endedAt": ended_at,
                "durationMs": 0,
                "error": {"name": "HostTestError", "message": message},
            }
        )
        return {**value, "status": "failed", "afterAll": after_all}

    summary = cast(TestRunReportSummary, dict(dump.get("summary") or {}))
    if document is not None:
        summary["documentFailures"] = summary.get("documentFailures", 0) + 1
    else:
        summary["projectFailures"] = summary.get("projectFailures", 0) + 1

    merged_projects: list[TestRunReportProject] = []
    for index, item in enumerate(projects):
        if index != project_index:
            merged_projects.append(item)
            continue
        merged_documents: list[TestRunReportDocument] = []
        for document_index_, value in enumerate(item.get("documents") or []):
            if document_index_ != document_index:
                merged_documents.append(value)
                continue
            replaced = cast(TestRunReportDocument, after_host(value))
            if value.get("attempts") is not None:
                attempts = list(value["attempts"])
                if attempts:
                    attempts[-1] = after_host(attempts[-1])
                replaced["attempts"] = attempts
            merged_documents.append(replaced)
        merged_projects.append(
            cast(
                TestRunReportProject,
                {**item, "status": "failed", "documents": merged_documents},
            )
        )

    # The enclosing test can fail after YAML succeeds. Record that outcome at
    # the file boundary instead of changing successful actions or Case attempts.
    diagnostics: list[TestRunReportDiagnostic] = list(dump.get("diagnostics") or [])
    diagnostics.append(
        {
            "level": "error",
            "code": "run-infrastructure-error",
            "message": message,
        }
    )
    return {
        **dump,
        "status": "failed",
        "summary": summary,
        "projects": merged_projects,
        "diagnostics": diagnostics,
    }


def merge_test_run_report_dumps(
    sources: list[MergeTestRunReportSource],
    metrics: TestRunReportMetrics,
    run_id: str,
    raw_execution_metrics: dict[str, TestRunReportMetrics] | None = None,
) -> TestRunReportDump:
    dumps: list[dict[str, Any]] = []
    for source in sources:
        source_dump = source.get("dump")
        if source_dump is not None:
            start = _parse_ms(source_dump.get("startedAt"))
            end = _parse_ms(source_dump.get("endedAt"))
            if start is None or end is None or end < start:
                raise ValueError(
                    "Invalid execution timestamps in Midscene Test report: "
                    f"{source.get('sourcePath')}"
                )
        retained = _retain_host_failure(source)
        dump: dict[str, Any] = dict(
            retained if retained is not None else _agent_report_as_test_run(source)
        )

        def id_for(value: str, source: MergeTestRunReportSource = source) -> str:
            return f"{source.get('reportId')}:{value}"

        def error(value: Any) -> dict[str, Any]:
            return _remap_error(value, id_for)

        def scope_errors(value: dict[str, Any]) -> dict[str, Any]:
            result = {**value}
            if value.get("setupError") is not None:
                result["setupError"] = error(value["setupError"])
            if value.get("teardownErrors") is not None:
                result["teardownErrors"] = [
                    error(item) for item in value["teardownErrors"]
                ]
            if value.get("hostErrors") is not None:
                result["hostErrors"] = [
                    {**host, "error": error(host.get("error"))}
                    for host in value["hostErrors"]
                ]
            return result

        def reference(value: dict[str, Any]) -> dict[str, Any]:
            result = {**value}
            if value.get("stepId"):
                result["stepId"] = id_for(value["stepId"])
            if value.get("scopeId"):
                result["scopeId"] = id_for(value["scopeId"])
            return result

        def cleanup(value: dict[str, Any] | None) -> dict[str, Any] | None:
            if value is None:
                return None
            result = {**value}
            if value.get("error") is not None:
                result["error"] = error(value["error"])
            if value.get("blockingOperations") is not None:
                result["blockingOperations"] = [
                    reference(item) for item in value["blockingOperations"]
                ]
            return result

        def scope_reports(
            report_ids: list[str] | None,
            source: MergeTestRunReportSource = source,
        ) -> list[str] | None:
            if report_ids:
                return [cast(str, source.get("reportId"))]
            return report_ids

        def step(
            value: dict[str, Any],
            source: MergeTestRunReportSource = source,
        ) -> dict[str, Any]:
            result = {**value, "id": id_for(cast(str, value.get("id")))}
            if value.get("error") is not None:
                result["error"] = error(value["error"])
            if value.get("evidenceCollection") is not None:
                evidence = {**value["evidenceCollection"]}
                if value["evidenceCollection"].get("errors") is not None:
                    evidence["errors"] = [
                        error(item) for item in value["evidenceCollection"]["errors"]
                    ]
                result["evidenceCollection"] = evidence
            if value.get("operations") is not None:
                events = []
                for event in value["operations"].get("events") or []:
                    mapped = {**event}
                    if event.get("error") is not None:
                        mapped["error"] = error(event["error"])
                    if event.get("stepId"):
                        mapped["stepId"] = id_for(event["stepId"])
                    if event.get("scopeId"):
                        mapped["scopeId"] = id_for(event["scopeId"])
                    if event.get("blockingOperations") is not None:
                        mapped["blockingOperations"] = [
                            reference(item) for item in event["blockingOperations"]
                        ]
                    events.append(mapped)
                result["operations"] = {**value["operations"], "events": events}
            if value.get("agentDetails") is not None:
                result["agentDetails"] = [
                    {**detail, "reportId": source.get("reportId")}
                    for detail in value["agentDetails"]
                ]
            if result.get("status") == "not-run" and result.get("blockedBy"):
                result["blockedBy"] = id_for(result["blockedBy"])
            return result

        def document_scope(value: dict[str, Any]) -> dict[str, Any]:
            result = scope_errors(value)
            if value.get("cleanup") is not None:
                result["cleanup"] = cleanup(value["cleanup"])
            if value.get("pendingOperations") is not None:
                result["pendingOperations"] = [
                    reference(item) for item in value["pendingOperations"]
                ]
            result["documentId"] = id_for(cast(str, value.get("documentId")))
            if value.get("logicalDocumentId"):
                result["logicalDocumentId"] = id_for(value["logicalDocumentId"])
            if value.get("documentRunId"):
                result["documentRunId"] = id_for(value["documentRunId"])
            result["beforeAll"] = [step(item) for item in value.get("beforeAll") or []]
            result["afterAll"] = [step(item) for item in value.get("afterAll") or []]
            scoped_reports = scope_reports(value.get("scopeReportIds"))
            if scoped_reports is not None:
                result["scopeReportIds"] = scoped_reports
            return result

        merged_projects: list[dict[str, Any]] = []
        for project in dump.get("projects") or []:
            merged_project = {
                **project,
                "projectId": id_for(project.get("projectId")),
                "collectionErrors": [
                    {
                        **item,
                        "error": error(item.get("error")),
                    }
                    for item in (project.get("collectionErrors") or [])
                ],
            }
            lifecycle = project.get("lifecycle")
            if lifecycle is not None:
                merged_lifecycle = scope_errors(lifecycle)
                if lifecycle.get("cleanup") is not None:
                    merged_lifecycle["cleanup"] = cleanup(lifecycle["cleanup"])
                if lifecycle.get("pendingOperations") is not None:
                    merged_lifecycle["pendingOperations"] = [
                        reference(item) for item in lifecycle["pendingOperations"]
                    ]
                merged_project["lifecycle"] = merged_lifecycle
            merged_documents: list[dict[str, Any]] = []
            for document in project.get("documents") or []:
                merged_document = document_scope(document)
                if document.get("attempts") is not None:
                    merged_document["attempts"] = [
                        document_scope(attempt) for attempt in document["attempts"]
                    ]
                merged_cases = []
                for test_case in document.get("cases") or []:
                    merged_attempts = []
                    for attempt in test_case.get("attempts") or []:
                        merged_attempt = scope_errors(attempt)
                        merged_attempt["attemptId"] = id_for(attempt.get("attemptId"))
                        if attempt.get("cleanup") is not None:
                            merged_attempt["cleanup"] = cleanup(attempt["cleanup"])
                        if attempt.get("pendingOperations") is not None:
                            merged_attempt["pendingOperations"] = [
                                reference(item) for item in attempt["pendingOperations"]
                            ]
                        merged_attempt["beforeEach"] = [
                            step(item) for item in attempt.get("beforeEach") or []
                        ]
                        merged_attempt["steps"] = [
                            step(item) for item in attempt.get("steps") or []
                        ]
                        merged_attempt["afterEach"] = [
                            step(item) for item in attempt.get("afterEach") or []
                        ]
                        scoped_reports = scope_reports(attempt.get("scopeReportIds"))
                        if scoped_reports is not None:
                            merged_attempt["scopeReportIds"] = scoped_reports
                        merged_attempts.append(merged_attempt)
                    merged_cases.append(
                        {
                            **test_case,
                            "caseId": id_for(test_case.get("caseId")),
                            "attempts": merged_attempts,
                        }
                    )
                merged_document["cases"] = merged_cases
                merged_documents.append(merged_document)
            merged_project["documents"] = merged_documents
            merged_projects.append(merged_project)

        merged_dump = {**dump, "projects": merged_projects}
        if dump.get("diagnostics") is not None:
            merged_diagnostics = []
            for diagnostic in dump["diagnostics"]:
                mapped = {**diagnostic}
                if diagnostic.get("error") is not None:
                    mapped["error"] = error(diagnostic["error"])
                if diagnostic.get("scopeId"):
                    mapped["scopeId"] = id_for(diagnostic["scopeId"])
                if diagnostic.get("stepId"):
                    mapped["stepId"] = id_for(diagnostic["stepId"])
                merged_diagnostics.append(mapped)
            merged_dump["diagnostics"] = merged_diagnostics
        dumps.append(merged_dump)

    # A report without recorded timestamps contributes outcomes, not the time
    # at which an unrelated merge command happened to run.
    recorded_times: list[dict[str, float]] = []
    for dump in dumps:
        if dump.get("startedAt") and dump.get("endedAt"):
            start = _parse_ms(dump["startedAt"])
            end = _parse_ms(dump["endedAt"])
            if start is not None and end is not None:
                recorded_times.append({"start": start, "end": end})
    if not recorded_times:
        raise ValueError(
            "Cannot merge Midscene Test reports without recorded execution timestamps."
        )
    started_at = _iso_ms(min(item["start"] for item in recorded_times))
    ended_at = _iso_ms(max(item["end"] for item in recorded_times))

    summary: TestRunReportSummary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "notRun": 0,
        "filtered": 0,
        "collectionErrors": 0,
        "documentFailures": 0,
        "projectFailures": 0,
    }
    for dump in dumps:
        dump_summary = dump.get("summary") or {}
        for key in _SUMMARY_KEYS:
            summary[key] += cast(int, dump_summary.get(key, 0))

    diagnostics: list[TestRunReportDiagnostic] = []
    for dump in dumps:
        diagnostics.extend(dump.get("diagnostics") or [])

    execution_metrics: dict[str, TestRunReportMetrics] = dict(
        raw_execution_metrics or {}
    )
    for source in sources:
        source_dump = source.get("dump")
        if source_dump is not None and source_dump.get("executionMetrics") is not None:
            execution_metrics.update(source_dump["executionMetrics"])

    if raw_execution_metrics is not None:
        additional = [
            value
            for execution_id, value in execution_metrics.items()
            if not raw_execution_metrics.get(execution_id)
        ]
        metrics = sum_test_run_report_metrics([metrics] + additional)
    elif all(
        (source_dump := source.get("dump")) is not None
        and source_dump.get("executionMetrics") is not None
        for source in sources
    ):
        metrics = sum_test_run_report_metrics(list(execution_metrics.values()))

    collections = []
    for source in sources:
        source_dump = source.get("dump")
        if source_dump is not None:
            collections.append((source_dump.get("metrics") or {}).get("collection"))

    metrics_collection = metrics.get("collection") or {}
    incomplete = metrics_collection.get("status") in ("partial", "unknown") or any(
        (collection or {}).get("status") != "complete" for collection in collections
    )
    if incomplete:
        has_recorded = metrics.get("modelCallCount", 0) > 0 or any(
            (collection or {}).get("status") in ("complete", "partial")
            for collection in collections
        )
        collection_status = "partial" if has_recorded else "unknown"
    else:
        collection_status = "complete"

    expected_execution_count = sum(
        (collection or {}).get("expectedExecutionCount") or 0
        for collection in collections
    )
    captured_execution_count = sum(
        (collection or {}).get("capturedExecutionCount") or 0
        for collection in collections
    )

    reasons = list(metrics_collection.get("reasons") or [])
    for collection in collections:
        collection_reasons = (collection or {}).get("reasons")
        if collection_reasons is None:
            collection_reasons = [
                "Model metric collection status is unavailable in a source report."
            ]
        for reason in collection_reasons:
            if reason not in reasons:
                reasons.append(reason)

    fields: dict[str, str] = {}
    for field in _METRIC_FIELDS:
        states: list[str | None] = []
        for collection in collections:
            state = None
            if collection is not None:
                state = (collection.get("fields") or {}).get(field)
                if state is None:
                    state = collection.get("status")
            states.append(state if state is not None else "unknown")
        if metrics_collection.get("fields") is not None:
            states.append(metrics_collection["fields"].get(field))
        if all(state == "complete" for state in states):
            fields[field] = "complete"
        elif all(state == "unknown" for state in states):
            fields[field] = "unknown"
        else:
            fields[field] = "partial"

    collection = {
        "status": collection_status,
        "expectedExecutionCount": expected_execution_count,
        "capturedExecutionCount": captured_execution_count,
        "reasons": reasons,
        "fields": fields,
    }

    start_ms = _parse_ms(started_at)
    end_ms = _parse_ms(ended_at)
    duration_ms = (
        max(0.0, end_ms - start_ms)
        if start_ms is not None and end_ms is not None
        else 0.0
    )

    result: TestRunReportDump = {
        "schemaVersion": 1,
        "kind": "test-runner",
        "runId": run_id,
        "status": (
            "failed"
            if any(dump.get("status") == "failed" for dump in dumps)
            else "success"
        ),
        "startedAt": started_at,
        "endedAt": ended_at,
        "durationMs": duration_ms,
        "summary": summary,
        "metrics": {**metrics, "collection": collection},
        "projects": [
            project for dump in dumps for project in (dump.get("projects") or [])
        ],
    }
    if execution_metrics:
        result["executionMetrics"] = execution_metrics
    if any(dump.get("operationLogs") for dump in dumps):
        result["operationLogs"] = [
            log for dump in dumps for log in (dump.get("operationLogs") or [])
        ]
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result


__all__ = ["MergeTestRunReportSource", "merge_test_run_report_dumps"]
