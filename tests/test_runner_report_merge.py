"""Synced from upstream packages/core/tests/unit-test/runner-report-merge.test.ts."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from midscene.core.dump.html_utils import (
    generate_dump_script_tag,
    generate_test_run_report_script_tag,
)
from midscene.core.dump.report_artifact_reader import read_report_runner_dump
from midscene.core.report import ReportMergingTool
from midscene.core.test_runner.reporting.merge_report import (
    merge_test_run_report_dumps,
)
from midscene.core.test_runner.reporting.metrics import sum_test_run_report_metrics
from midscene.core.test_runner.reporting.test_run_report import (
    build_test_run_report_dump,
)
from midscene.core.utils import get_version

_TIME = "2026-09-10T00:00:00.000Z"
_TIME_MS = int(
    datetime.strptime(_TIME, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp()
    * 1000
)


def _runner_step(step_id: str, report_id: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "phase": "steps",
        "stepIndex": 0,
        "node": "aiAct",
        "title": "Submit",
        "status": "success",
        "continuedAfterError": False,
        "startedAt": _TIME,
        "endedAt": _TIME,
        "durationMs": 0,
        "agentDetails": [{"reportId": report_id, "executionId": "shared-execution"}],
    }


def _runner_dump(report_id: str) -> dict[str, Any]:
    lifecycle = {
        "documentId": "document",
        "sourcePath": "/fixtures/case.yaml",
        "status": "success",
        "beforeAll": [{**_runner_step("setup", report_id), "phase": "beforeAll"}],
        "afterAll": [],
        "scopeReportIds": [report_id],
    }

    def attempt(attempt_index: int, status: str = "success") -> dict[str, Any]:
        return {
            **lifecycle,
            "documentRunId": f"file-attempt-{attempt_index + 1}",
            "attemptIndex": attempt_index,
            "status": status,
            **(
                {"teardownErrors": [{"name": "Error", "message": "old cleanup failed"}]}
                if status == "failed"
                else {}
            ),
        }

    return {
        "schemaVersion": 1,
        "kind": "test-runner",
        "runId": "run",
        "status": "success",
        "startedAt": _TIME,
        "endedAt": _TIME,
        "durationMs": 0,
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
        "metrics": {
            "modelCallCount": 7,
            "modelTimeMs": 100,
            "promptTokens": 99,
            "cachedInputTokens": 0,
            "completionTokens": 1,
            "totalTokens": 100,
        },
        "projects": [
            {
                "projectId": "project",
                "name": "web",
                "platform": "web",
                "status": "success",
                "retry": 1,
                "collectionErrors": [],
                "documents": [
                    {
                        **lifecycle,
                        "logicalDocumentId": "document",
                        "documentRunId": "file-attempt-2",
                        "attemptIndex": 1,
                        "attempts": [
                            attempt(0, "failed"),
                            attempt(1),
                        ],
                        "cases": [
                            {
                                "caseId": "case",
                                "name": "submit",
                                "caseIndex": 0,
                                "status": "success",
                                "attempts": [
                                    {
                                        "attemptId": f"attempt-{index}",
                                        "attemptIndex": index,
                                        "status": ("success" if index else "failed"),
                                        "startedAt": _TIME,
                                        "endedAt": _TIME,
                                        "durationMs": 0,
                                        "beforeEach": [],
                                        "afterEach": [],
                                        "steps": [
                                            _runner_step(f"step-{index}", report_id)
                                        ],
                                        "scopeReportIds": [report_id],
                                    }
                                    for index in (0, 1)
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _write_source(directory: Path, name: str, dump: dict[str, Any]) -> str:
    report_path = directory / f"{name}.html"
    agent = {
        "sdkVersion": get_version(),
        "groupName": name,
        "groupDescription": None,
        "modelBriefs": [],
        "executions": [
            {
                "id": "shared-execution",
                "name": "Submit",
                "logTime": _TIME_MS,
                "tasks": [
                    {
                        "taskId": "assert",
                        "type": "Insight",
                        "subType": "Assert",
                        "status": "finished",
                        "param": {},
                        "recorder": [],
                    }
                ],
            }
        ],
    }
    content = generate_dump_script_tag(
        json.dumps(agent),
        {
            "data-group-id": f"{name}-group",
            "data-report-id": f"{name}-group",
        },
    )
    content += "\n" + generate_test_run_report_script_tag(dump)
    report_path.write_text(content, encoding="utf-8")
    return str(report_path)


def _step(
    node: str = "echo", meta: dict[str, Any] = None, **input_value
) -> dict[str, Any]:
    return {
        "node": node,
        "input": input_value,
        "meta": meta or {"continueOnError": False},
    }


def _document(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "documentId": "doc-1",
        "projectId": "project-1",
        "sourcePath": "/tmp/workflow.yaml",
        "lifecycle": {
            "beforeAll": [],
            "beforeEach": [],
            "afterEach": [],
            "afterAll": [],
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


@pytest.mark.parametrize("test_status", ["failed", "timedOut", "interrupted"])
def test_retains_host_status_without_changing_successful_yaml_actions(
    tmp_path, test_status
):
    source_dump = _runner_dump("yaml-group")
    source = _write_source(tmp_path, "yaml", source_dump)

    tool = ReportMergingTool()
    tool.append(
        {
            "reportFilePath": source,
            "reportAttributes": {
                "testTitle": "outer test",
                "testId": "outer",
                "testDescription": "",
                "testDuration": 100,
                "testStatus": test_status,
            },
        }
    )
    output = tool.merge_reports("host-failed", {"outputDir": str(tmp_path)})
    assert output is not None

    merged = read_report_runner_dump(output)
    assert merged["status"] == "failed"
    assert merged["summary"]["total"] == 1
    assert merged["summary"]["passed"] == 1
    assert merged["summary"]["failed"] == 0
    assert merged["summary"]["documentFailures"] == 1
    assert merged["projects"][0]["status"] == "failed"

    document = merged["projects"][0]["documents"][0]
    assert document["status"] == "failed"
    host_result = document["afterAll"][-1]
    assert host_result["node"] == "runner:host-result"
    assert host_result["status"] == "failed"
    assert test_status in host_result["error"]["message"]
    assert document["attempts"][-1]["afterAll"][-1]["node"] == ("runner:host-result")
    assert [attempt["status"] for attempt in document["cases"][0]["attempts"]] == [
        "failed",
        "success",
    ]
    assert document["cases"][0]["attempts"][-1]["steps"][0]["status"] == ("success")
    assert source_dump["status"] == "success"

    second_tool = ReportMergingTool()
    second_tool.append({"reportFilePath": output})
    second = second_tool.merge_reports("again", {"outputDir": str(tmp_path)})
    assert second is not None
    assert read_report_runner_dump(second)["summary"]["documentFailures"] == 1
