"""Synced from upstream packages/core/tests/unit-test/runner-report-projection.test.ts.

Only the projection cases represented by the former aggregate suite are
synced; the upstream cases that build whole-file retry histories through
ScriptPlayer remain covered by their own upstream-named suites.
"""

from typing import Any

import pytest

from midscene.core.test_runner.reporting.execution_record import (
    execution_records_to_report_input,
)
from midscene.core.test_runner.reporting.test_run_report import (
    build_test_run_report_dump,
)


def _step(
    node: str = "echo", meta: dict[str, Any] = None, **input_value
) -> dict[str, Any]:
    return {
        "node": node,
        "input": input_value,
        "meta": meta or {"continueOnError": False},
    }


def _document(steps: list[dict[str, Any]], **lifecycle) -> dict[str, Any]:
    return {
        "documentId": "doc-1",
        "projectId": "project-1",
        "sourcePath": "/tmp/workflow.yaml",
        "lifecycle": {
            "beforeAll": lifecycle.get("beforeAll", []),
            "beforeEach": lifecycle.get("beforeEach", []),
            "afterEach": lifecycle.get("afterEach", []),
            "afterAll": lifecycle.get("afterAll", []),
        },
        "cases": [
            {
                "caseId": "case-1",
                "projectId": "project-1",
                "sourcePath": "/tmp/workflow.yaml",
                "caseIndex": 0,
                "definition": {"name": "case one", "tags": ["smoke"], "steps": steps},
            }
        ],
    }


def _record(**overrides):
    record = {
        "runId": "run-1",
        "attemptIndex": 0,
        "sourcePath": "/tmp/workflow.yaml",
        "platform": "cli",
        "document": _document([_step(prompt="hi")]),
        "status": "success",
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T00:00:01.000Z",
        "durationMs": 1000,
        "cleanupErrors": [],
        "outputs": {},
        "reportPaths": [],
    }
    record.update(overrides)
    return record


def _report_step(**overrides):
    step = {
        "phase": "steps",
        "stepIndex": 0,
        "node": "echo",
        "input": {"prompt": "say hi"},
        "status": "success",
        "continuedAfterError": False,
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T00:00:00.500Z",
        "durationMs": 500,
        "output": {"summary": "ok", "data": {"value": 1}},
    }
    step.update(overrides)
    return step


def _report_attempt(**overrides):
    attempt = {
        "runId": "case-run-1",
        "attemptIndex": 0,
        "status": "success",
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T00:00:01.000Z",
        "durationMs": 1000,
        "beforeEach": [],
        "steps": [_report_step()],
        "afterEach": [],
    }
    attempt.update(overrides)
    return attempt


def _report_input(**overrides):
    document = {
        "documentId": "doc-1",
        "documentRunId": "doc-run-1",
        "attemptIndex": 0,
        "sourcePath": "/tmp/workflow.yaml",
        "status": "success",
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T00:00:02.000Z",
        "durationMs": 2000,
        "beforeAll": [],
        "afterAll": [],
    }
    report = {
        "runId": "batch-1",
        "status": "success",
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T00:00:02.000Z",
        "durationMs": 2000,
        "summary": {
            "total": 1,
            "passed": 1,
            "failed": 0,
            "notRun": 0,
            "filtered": 0,
            "collectionErrors": 0,
            "documentFailures": 0,
            "projectFailures": 0,
        },
        "projects": [
            {
                "projectId": "project-1",
                "name": "Project One",
                "platform": "cli",
                "status": "success",
                "retry": 0,
                "documents": [document],
                "cases": [
                    {
                        "caseId": "case-1",
                        "name": "case one",
                        "caseIndex": 0,
                        "status": "success",
                        "run": _report_attempt(),
                        "documentId": "doc-1",
                        "documentRunId": "doc-run-1",
                    }
                ],
                "collectionErrors": [],
            }
        ],
        "errors": [],
    }
    report.update(overrides)
    return report


def test_shows_setup_failure_with_not_run_tasks_even_without_a_kernel_result():
    from midscene.core.test_runner.execution_record import execution_record_to_result

    result = execution_record_to_result(_record())
    assert result["document"]["documentRunId"] == "run-1"
    assert result["document"]["status"] == "success"
    assert result["document"]["plan"]["documentId"] == "doc-1"
    assert result["cases"][0]["status"] == "not-run"
    assert result["cases"][0]["notRunReason"] == "document-start-failed"

    failed = execution_record_to_result(_record(setupError=RuntimeError("no env")))
    document = failed["document"]
    assert document["status"] == "failed"
    assert [host["phase"] for host in document["hostErrors"]] == ["setup"]


def test_preserves_whole_file_retry_history_while_summarizing_the_final_outcome():
    records = [
        _record(runId="run-1"),
        _record(
            runId="run-2",
            attemptIndex=1,
            status="failed",
            execution={
                "document": {"status": "success", "cases": []},
                "cases": [
                    {"caseId": "case-1", "status": "failed"},
                ],
            },
        ),
    ]
    report = execution_records_to_report_input(records, {"runId": "batch-1"})
    assert report["status"] == "failed"
    assert report["summary"]["total"] == 1
    assert report["summary"]["failed"] == 1
    assert len(report["projects"][0]["documents"]) == 2
    assert report["projects"][0]["retry"] == 1
    run_ids = {case["documentRunId"] for case in report["projects"][0]["cases"]}
    assert run_ids == {"run-1", "run-2"}


def test_uses_execution_identities_even_when_legacy_tasks_share_one_agent():
    dump = build_test_run_report_dump(
        _report_input(), {"sources": [], "metrics": {}, "diagnostics": []}
    )
    project = dump["projects"][0]
    assert project["platform"] == "cli"
    document = project["documents"][0]
    assert document["documentRunId"] == "doc-run-1"
    case = document["cases"][0]
    assert case["status"] == "success"
    step = case["attempts"][0]["steps"][0]
    assert step["id"] == "case-run-1:steps:0"
    assert step["title"] == "say hi"
    assert step["input"] == {"value": {"prompt": "say hi"}}
    assert step["output"] == {"summary": "ok", "data": {"value": {"value": 1}}}
    assert dump["metrics"]["collection"]["status"] == "complete"


def test_retains_captured_usage_even_when_an_external_source_lacks_execution_ids():
    metrics = {
        "modelCallCount": 1,
        "modelTimeMs": 100,
        "promptTokens": 3,
        "cachedInputTokens": 0,
        "completionTokens": 2,
        "totalTokens": 5,
    }
    report = _report_input()
    report["projects"][0]["documents"][0]["reportScopeId"] = "scope-1"
    report["projects"][0]["documents"][0]["beforeAll"] = [
        _report_step(
            phase="beforeAll",
            report={
                "traces": [{"executionId": "exec-1", "metrics": metrics}],
                "sources": [
                    {
                        "sourcePath": "/tmp/report.json",
                        "collection": {
                            "status": "complete",
                            "capturedAt": "2026-01-01T00:00:02.000Z",
                        },
                    }
                ],
            },
        )
    ]
    dump = build_test_run_report_dump(
        report,
        {
            "sources": [
                {
                    "reportId": "report-1",
                    "scopeId": "scope-1",
                    "sourcePath": "/tmp/report.json",
                    "executionIds": ["exec-1"],
                }
            ],
            "metrics": {},
            "diagnostics": [],
        },
    )
    document = dump["projects"][0]["documents"][0]
    step = document["beforeAll"][0]
    assert step["agentDetails"] == [{"reportId": "report-1", "executionId": "exec-1"}]
    assert step["metrics"]["modelCallCount"] == 1
    assert step["evidenceCollection"]["status"] == "complete"
    assert document["scopeReportIds"] == ["report-1"]
    collection = dump["metrics"]["collection"]
    assert collection["expectedExecutionCount"] == 1
    assert collection["capturedExecutionCount"] == 1
    assert dump["executionMetrics"]["exec-1"]["totalTokens"] == 5


def test_retains_independently_captured_usage_when_agent_detail_storage_fails():
    report = _report_input()
    report["projects"][0]["documents"][0]["reportScopeId"] = "scope-1"
    report["projects"][0]["documents"][0]["beforeAll"] = [
        _report_step(
            phase="beforeAll",
            report={"traces": [{"executionId": "exec-missing"}]},
        )
    ]
    dump = build_test_run_report_dump(
        report,
        {"sources": [], "metrics": {}, "diagnostics": []},
    )
    step = dump["projects"][0]["documents"][0]["beforeAll"][0]
    assert "exec-missing" in step["agentDetailDiagnostic"]
    assert step["evidenceCollection"] == {
        "status": "unknown",
        "modelUsageUnavailable": True,
    }
    diagnostics = [
        item
        for item in dump["diagnostics"]
        if item["code"] == "agent-detail-unresolved"
    ]
    assert diagnostics and diagnostics[0]["executionId"] == "exec-missing"
    assert dump["metrics"]["collection"]["status"] == "unknown"


def test_retains_multiple_whole_file_attempts_instead_of_overwriting_by_document_id():
    report = _report_input()
    project = report["projects"][0]
    first = project["documents"][0]
    second = dict(first, documentRunId="doc-run-2", attemptIndex=1)
    project["documents"] = [first, second]
    project["cases"] = [
        {
            "caseId": "case-1",
            "name": "case one",
            "caseIndex": 0,
            "status": "failed",
            "run": _report_attempt(runId="case-run-1"),
            "documentId": "doc-1",
            "documentRunId": "doc-run-1",
        },
        {
            "caseId": "case-1",
            "name": "case one",
            "caseIndex": 0,
            "status": "success",
            "run": _report_attempt(runId="case-run-2"),
            "documentId": "doc-1",
            "documentRunId": "doc-run-2",
        },
    ]
    dump = build_test_run_report_dump(
        report, {"sources": [], "metrics": {}, "diagnostics": []}
    )
    documents = dump["projects"][0]["documents"]
    assert len(documents) == 1
    document = documents[0]
    assert document["documentRunId"] == "doc-run-2"
    assert len(document["attempts"]) == 2
    assert [item["attemptIndex"] for item in document["attempts"]] == [0, 1]
    case = document["cases"][0]
    assert case["status"] == "success"
    assert [item["attemptId"] for item in case["attempts"]] == [
        "case-run-1",
        "case-run-2",
    ]

    ambiguous = _report_input()
    ambiguous_project = ambiguous["projects"][0]
    ambiguous_first = ambiguous_project["documents"][0]
    ambiguous_project["documents"] = [
        ambiguous_first,
        dict(ambiguous_first, documentRunId="doc-run-2", attemptIndex=1),
    ]
    ambiguous_project["cases"][0].pop("documentRunId")
    with pytest.raises(ValueError):
        build_test_run_report_dump(
            ambiguous, {"sources": [], "metrics": {}, "diagnostics": []}
        )
