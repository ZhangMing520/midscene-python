"""Synced from upstream packages/core/tests/unit-test/runner-report-merge.test.ts.

The Python port exposes merge_test_run_report_dumps (pure dump merging) but no
ReportMergingTool/mergeReportFiles HTML orchestration, so the host-status case
is skipped. The remaining cases keep the upstream names and asserted ids.
"""

from typing import Any, Dict, List

import pytest

from midscene.core.test_runner.reporting.merge_report import (
    merge_test_run_report_dumps,
)
from midscene.core.test_runner.reporting.metrics import sum_test_run_report_metrics
from midscene.core.test_runner.reporting.test_run_report import (
    build_test_run_report_dump,
)


def _step(node: str = "echo", meta: Dict[str, Any] = None, **input_value) -> Dict[str, Any]:
    return {
        "node": node,
        "input": input_value,
        "meta": meta or {"continueOnError": False},
    }


def _document(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "documentId": "doc-1",
        "projectId": "project-1",
        "sourcePath": "/tmp/workflow.yaml",
        "lifecycle": {"beforeAll": [], "beforeEach": [], "afterEach": [], "afterAll": []},
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


def _built_dump(**overrides):
    return build_test_run_report_dump(
        _report_input(**overrides),
        {"sources": [], "metrics": {}, "diagnostics": []},
    )


def test_preserves_retry_hierarchy_and_remaps_every_trace_when_ids_overlap_across_inputs():
    first = _built_dump()
    second = _built_dump(runId="batch-2")
    merged = merge_test_run_report_dumps(
        [
            {
                "reportId": "report-a",
                "sourcePath": "/tmp/a.json",
                "attributes": {"testStatus": "passed"},
                "dump": first,
            },
            {
                "reportId": "report-b",
                "sourcePath": "/tmp/b.json",
                "attributes": {"testStatus": "passed"},
                "dump": second,
            },
        ],
        first["metrics"],
        "merged-1",
    )
    assert merged["runId"] == "merged-1"
    assert merged["status"] == "success"
    assert merged["summary"]["total"] == 2
    assert merged["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert merged["endedAt"] == "2026-01-01T00:00:02.000Z"
    assert [project["projectId"] for project in merged["projects"]] == [
        "report-a:project-1",
        "report-b:project-1",
    ]
    document = merged["projects"][0]["documents"][0]
    assert document["documentId"] == "report-a:doc-1"
    case = document["cases"][0]
    assert case["caseId"] == "report-a:case-1"
    assert case["attempts"][0]["attemptId"] == "report-a:case-run-1"
    assert case["attempts"][0]["steps"][0]["id"] == "report-a:case-run-1:steps:0"
    assert merged["metrics"]["collection"]["status"] == "complete"


def test_keeps_agent_only_inputs_browsable_when_mixed_with_a_test_report():
    merged = merge_test_run_report_dumps(
        [
            {
                "reportId": "agent-1",
                "sourcePath": "/tmp/agent.json",
                "attributes": {
                    "testStatus": "passed",
                    "testTitle": "agent case",
                    "testId": "agent-case",
                },
                "timing": {
                    "startedAt": "2026-01-01T00:00:00.000Z",
                    "endedAt": "2026-01-01T00:00:01.000Z",
                    "durationMs": 1000,
                },
            }
        ],
        sum_test_run_report_metrics([]),
        "merged-3",
    )
    project = merged["projects"][0]
    assert project["projectId"] == "agent-1:agent-report"
    assert project["platform"] == "agent"
    case = project["documents"][0]["cases"][0]
    assert case["status"] == "success"
    assert case["attempts"][0]["attemptId"] == "agent-1:agent-report"
    assert merged["status"] == "success"


def test_rejects_an_invalid_source_execution_timestamp():
    dump = _built_dump()
    dump["startedAt"] = "not-a-date"
    with pytest.raises(ValueError):
        merge_test_run_report_dumps(
            [
                {
                    "reportId": "report-a",
                    "sourcePath": "/tmp/a.json",
                    "attributes": {"testStatus": "passed"},
                    "dump": dump,
                }
            ],
            dump["metrics"],
            "merged-4",
        )
    with pytest.raises(ValueError):
        merge_test_run_report_dumps(
            [
                {
                    "reportId": "agent-1",
                    "sourcePath": "/tmp/agent.json",
                    "attributes": {"testStatus": "skipped"},
                }
            ],
            dump["metrics"],
            "merged-5",
        )


@pytest.mark.skip(
    reason="Python has no ReportMergingTool/mergeReportFiles host-status pipeline; "
    "retaining a host failure requires the HTML report merger"
)
def test_retains_host_status_without_changing_successful_yaml_actions():
    pass
