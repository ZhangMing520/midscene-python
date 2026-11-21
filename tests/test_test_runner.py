"""Smoke coverage for the ported workflow test-runner engine."""

import asyncio
from typing import Any, Dict, List

import pytest

from midscene.core.test_runner.engine.case_runner import CaseRunner
from midscene.core.test_runner.engine.execute_step import execute_step
from midscene.core.test_runner.engine.project_runtime import create_project_runtime
from midscene.core.test_runner.engine.registry import NodeRegistry
from midscene.core.test_runner.engine.resource_operations import (
    create_resource_scope,
    get_resource_cleanup_snapshot,
)
from midscene.core.test_runner.engine.result_metadata import decide_retry, phase_result
from midscene.core.test_runner.engine.run_collected_case import run_collected_case
from midscene.core.test_runner.engine.run_workflow_document import (
    run_workflow_document,
)
from midscene.core.test_runner.engine.scheduler import (
    run_concurrent_jobs,
    run_document_attempts,
)
from midscene.core.test_runner.errors import (
    DuplicateNodeError,
    NodeExecutionError,
    NodeNotFoundError,
)
from midscene.core.test_runner.node.define_node import define_node
from midscene.core.test_runner.reporting.metrics import (
    collect_test_run_report_metrics,
    sum_test_run_report_metrics,
)
from midscene.core.test_runner.reporting.sanitize import sanitize_report_value
from midscene.core.test_runner.reporting.test_plan import build_test_run_report_plan


def _step(node: str = "echo", meta: Dict[str, Any] = None, **input_value) -> Dict[str, Any]:
    return {
        "node": node,
        "input": input_value,
        "meta": meta or {"continueOnError": False},
    }


def _document(steps: List[Dict[str, Any]], **lifecycle) -> Dict[str, Any]:
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


def _echo_node():
    async def execute(ctx):
        return {"summary": "ok", "data": dict(ctx.input)}

    return define_node("echo", execute)


def test_registry_rejects_duplicates_and_missing():
    registry = NodeRegistry([_echo_node()])
    assert registry.has("echo")
    assert registry.require("echo").name == "echo"
    with pytest.raises(DuplicateNodeError):
        registry.register(_echo_node())
    with pytest.raises(NodeNotFoundError):
        registry.require("missing")


def test_phase_result_and_retry_metadata():
    assert phase_result(0, [])["status"] == "not-required"
    assert phase_result(2, [{"status": "success"}, {"status": "failed"}])[
        "status"
    ] == "failed"
    assert phase_result(2, [{"status": "success"}, {"status": "not-run"}])[
        "status"
    ] == "not-run"
    decision = decide_retry(
        {
            "scope": "case",
            "retryCount": 2,
            "attemptIndex": 0,
            "status": "failed",
            "cleanupPending": True,
        }
    )
    assert decision["decision"] == "stop"
    assert decision["reason"] == "cleanup-pending"


def test_sanitize_report_value_bounds_strings():
    assert sanitize_report_value("short") == {"value": "short"}
    bounded = sanitize_report_value("x" * 5000)
    assert bounded["value"].endswith("[truncated]")
    assert "truncatedPaths" in bounded


@pytest.mark.asyncio
async def test_execute_step_success_and_failure():
    node = _echo_node()
    target = {
        "scope": "case",
        "case": {"runId": "run-1", "phase": "steps", "stepIndex": 0},
    }
    result = await execute_step(_step(prompt="hello"), node, target, None, {})
    assert result["status"] == "success"
    assert result["output"]["data"] == {"prompt": "hello"}

    async def boom(ctx):
        raise RuntimeError("kaboom")

    failing = define_node("boom", boom)
    failed = await execute_step(
        _step("boom", {"continueOnError": True}), failing, target, None, {}
    )
    assert failed["status"] == "failed"
    assert failed["continuedAfterError"] is True
    assert failed["error"].code == "NODE_EXECUTION_ERROR"


@pytest.mark.asyncio
async def test_execute_step_times_out():
    async def slow(ctx):
        await asyncio.sleep(5)
        return {"summary": "late"}

    node = define_node("slow", slow)
    step = _step("slow", meta={"timeoutMs": 20, "continueOnError": False})
    result = await execute_step(
        step,
        node,
        {"scope": "case", "case": {"runId": "run-1", "phase": "steps", "stepIndex": 0}},
        None,
        {},
    )
    assert result["status"] == "failed"
    assert result["error"].code == "STEP_TIMEOUT"


@pytest.mark.asyncio
async def test_case_runner_runs_steps_and_raises_fatal_error():
    runner = CaseRunner({"nodes": [_echo_node()]})
    result = await runner.run(
        {"name": "standalone", "steps": [{"echo": {"prompt": "hi"}}]}
    )
    assert result["status"] == "success"
    assert result["steps"][0]["status"] == "success"

    async def boom(ctx):
        raise RuntimeError("kaboom")

    runner.register(define_node("boom", boom))
    with pytest.raises(NodeExecutionError):
        await runner.run({"steps": [{"boom": {"x": 1}}]})


@pytest.mark.asyncio
async def test_run_collected_case_runs_lifecycle_and_teardown():
    events: List[str] = []

    async def echo(ctx):
        events.append(ctx.meta.get("tag", "step"))
        return {"summary": "ok"}

    node = define_node("echo", echo)
    document = _document(
        [_step(prompt="step")],
        beforeAll=[_step(prompt="beforeAll")],
        beforeEach=[_step(prompt="beforeEach")],
        afterEach=[_step(prompt="afterEach")],
        afterAll=[_step(prompt="afterAll")],
    )
    collected = dict(document["cases"][0])
    result = await run_collected_case(
        collected,
        {
            "resolveNode": lambda name: node,
            "beforeEach": document["lifecycle"]["beforeEach"],
            "afterEach": document["lifecycle"]["afterEach"],
            "context": None,
            "projectName": "project-1",
        },
    )
    assert result["status"] == "success"
    assert len(result["steps"]) == 1
    assert len(result["afterEach"]) == 1
    assert result["phases"]["steps"]["status"] == "success"


@pytest.mark.asyncio
async def test_run_workflow_document_runs_hooks_and_retries():
    attempts = {"count": 0}

    async def flaky(ctx):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("first attempt")
        return {"summary": "ok"}

    async def hook(ctx):
        return {"summary": "hook"}

    nodes = {
        "flaky": define_node("flaky", flaky),
        "hook": define_node("hook", hook),
    }
    document = _document(
        [_step("flaky", x=1)],
        beforeAll=[_step("hook")],
        afterAll=[_step("hook")],
    )
    result = await run_workflow_document(
        document, {"resolveNode": lambda name: nodes[name], "retry": 1}
    )
    assert result["document"]["status"] == "success"
    assert result["cases"][0]["status"] == "success"
    assert len(result["cases"][0]["attempts"]) == 2
    assert result["document"]["beforeAll"][0]["status"] == "success"
    assert result["document"]["afterAll"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_run_workflow_document_reports_failure_outcome():
    async def boom(ctx):
        raise RuntimeError("nope")

    node = define_node("boom", boom)
    document = _document([_step("boom", x=1)])
    result = await run_workflow_document(document, {"resolveNode": lambda _: node})
    assert result["cases"][0]["status"] == "failed"
    assert result["document"]["status"] == "success"


@pytest.mark.asyncio
async def test_project_runtime_setup_and_teardown_order():
    order: List[str] = []

    async def setup(ctx):
        order.append("setup")
        ctx["onTeardown"](lambda teardown_ctx: order.append("teardown"))
        return {"ready": True}

    runtime = create_project_runtime(
        {
            "project": {"projectId": "p1", "name": "P1"},
            "setup": {"name": "setup", "setup": setup},
        }
    )
    started = await runtime.start()
    assert started["status"] == "success"
    assert runtime.can_run is True
    assert runtime.context == {"ready": True}
    finished = await runtime.finish()
    assert finished["status"] == "success"
    assert order == ["setup", "teardown"]


@pytest.mark.asyncio
async def test_project_runtime_setup_failure_blocks_cases():
    async def bad_setup(ctx):
        raise RuntimeError("no environment")

    runtime = create_project_runtime(
        {
            "project": {"projectId": "p2", "name": "P2"},
            "setup": {"name": "setup", "setup": bad_setup},
        }
    )
    started = await runtime.start()
    assert started["status"] == "failed"
    assert started["setupError"].code == "PROJECT_SETUP_ERROR"
    assert runtime.can_run is False


def test_test_run_report_plan_snapshots_steps():
    document = _document([_step(prompt="say hi")])
    plan = build_test_run_report_plan(document, {"defaultTimeoutMs": 1000})
    assert plan["documentId"] == "doc-1"
    assert plan["cases"][0]["caseId"] == "case-1"
    assert plan["cases"][0]["steps"][0]["id"] == "doc-1:case-1:steps:0"
    assert plan["cases"][0]["steps"][0]["timeoutMs"] == 1000


@pytest.mark.asyncio
async def test_scheduler_retries_and_bounded_concurrency():
    order: List[int] = []

    async def run(index: int) -> str:
        order.append(index)
        return "failed" if index < 1 else "success"

    await run_document_attempts({"retry": 2}, run)
    assert order == [0, 1]

    seen: List[int] = []

    async def job(item: Any, index: int) -> None:
        seen.append(item)

    await run_concurrent_jobs([1, 2, 3], {"concurrency": 2}, job)
    assert sorted(seen) == [1, 2, 3]


def test_collect_report_metrics_flags_missing_usage():
    report = {
        "executions": [
            {
                "tasks": [
                    {
                        "status": "finished",
                        "timing": {"start": 1000, "end": 1200},
                        "usage": {
                            "model_name": "mock",
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                            "time_cost": 200,
                        },
                    },
                    {
                        "status": "running",
                        "timing": {"start": 1300},
                    },
                ]
            }
        ]
    }
    metrics = collect_test_run_report_metrics(report)
    assert metrics["modelCallCount"] == 1
    assert metrics["totalTokens"] == 15
    assert metrics["collection"]["status"] == "partial"
    assert metrics["collection"]["fields"]["totalTokens"] == "partial"
    assert metrics["collection"]["reasons"]

    summed = sum_test_run_report_metrics(
        [metrics, metrics], missing_reasons=["missing report"]
    )
    assert summed["modelCallCount"] == 2
    assert summed["totalTokens"] == 30
    assert len(summed["models"]) == 1
    assert summed["collection"]["status"] == "partial"


@pytest.mark.asyncio
async def test_resource_scope_snapshot_and_dispose():
    scope = create_resource_scope()
    snapshot = get_resource_cleanup_snapshot(scope.signal)
    assert snapshot["status"] == "not-required"
    scope.dispose()


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


def test_execution_record_without_execution_is_not_run():
    from midscene.core.test_runner.execution_record import execution_record_to_result

    result = execution_record_to_result(_record())
    assert result["document"]["documentRunId"] == "run-1"
    assert result["document"]["status"] == "success"
    assert result["document"]["plan"]["documentId"] == "doc-1"
    assert result["cases"][0]["status"] == "not-run"
    assert result["cases"][0]["notRunReason"] == "document-start-failed"


def test_execution_record_surfaces_host_errors():
    from midscene.core.test_runner.execution_record import execution_record_to_result

    result = execution_record_to_result(
        _record(setupError=RuntimeError("no env"))
    )
    document = result["document"]
    assert document["status"] == "failed"
    phases = [host["phase"] for host in document["hostErrors"]]
    assert phases == ["setup"]


def test_execution_records_project_latest_invocation():
    from midscene.core.test_runner.reporting.execution_record import (
        execution_records_to_report_input,
    )

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
    # Only the latest invocation of a document counts toward the summary.
    assert report["summary"]["total"] == 1
    assert report["summary"]["failed"] == 1
    # Both invocations are projected, but only the latest counts for status.
    assert len(report["projects"][0]["documents"]) == 2
    assert report["projects"][0]["retry"] == 1
    run_ids = {case["documentRunId"] for case in report["projects"][0]["cases"]}
    assert run_ids == {"run-1", "run-2"}


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


def test_build_test_run_report_dump_projects_steps():
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

    dump = build_test_run_report_dump(
        _report_input(),
        {"sources": [], "metrics": {}, "diagnostics": []},
    )
    assert dump["schemaVersion"] == 1
    assert dump["kind"] == "test-runner"
    assert dump["runId"] == "batch-1"
    assert dump["summary"]["total"] == 1

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


def test_build_test_run_report_dump_resolves_agent_details():
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

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


def test_build_test_run_report_dump_flags_unresolved_agent_details():
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

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
    diagnostics = [item for item in dump["diagnostics"] if item["code"] == "agent-detail-unresolved"]
    assert diagnostics and diagnostics[0]["executionId"] == "exec-missing"
    assert dump["metrics"]["collection"]["status"] == "unknown"


def test_collect_test_run_report_sources_deduplicates_paths():
    from midscene.core.test_runner.reporting.test_run_report import (
        collect_test_run_report_sources,
    )

    report = _report_input()
    document = report["projects"][0]["documents"][0]
    document["reportSources"] = [{"sourcePath": "/tmp/a.json"}]
    document["reportPaths"] = ["/tmp/a.json", "/tmp/b.json"]
    attempt = report["projects"][0]["cases"][0]["run"]
    attempt["reportSources"] = [{"sourcePath": "/tmp/c.json", "dumpPath": "/tmp/c.dump"}]
    attempt["reportPaths"] = ["/tmp/c.json", "/tmp/d.json"]

    sources = collect_test_run_report_sources(report)
    assert sources == [
        {"scopeId": "doc-run-1", "sourcePath": "/tmp/a.json"},
        {"scopeId": "doc-run-1", "sourcePath": "/tmp/b.json"},
        {
            "scopeId": "case-run-1",
            "sourcePath": "/tmp/c.json",
            "dumpPath": "/tmp/c.dump",
        },
        {"scopeId": "case-run-1", "sourcePath": "/tmp/d.json"},
    ]


def test_build_test_run_report_dump_groups_document_attempts():
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

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


def _built_dump(**overrides):
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

    return build_test_run_report_dump(
        _report_input(**overrides),
        {"sources": [], "metrics": {}, "diagnostics": []},
    )


def test_merge_test_run_report_dumps_namespaces_ids():
    from midscene.core.test_runner.reporting.merge_report import (
        merge_test_run_report_dumps,
    )

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


def test_merge_test_run_report_dumps_retains_host_failure():
    from midscene.core.test_runner.reporting.merge_report import (
        merge_test_run_report_dumps,
    )

    dump = _built_dump()
    merged = merge_test_run_report_dumps(
        [
            {
                "reportId": "report-a",
                "sourcePath": "/tmp/a.json",
                "attributes": {
                    "testStatus": "failed",
                    "testTitle": "host case",
                    "testId": "host-1",
                },
                "dump": dump,
            }
        ],
        dump["metrics"],
        "merged-2",
    )
    assert merged["status"] == "failed"
    assert merged["summary"]["documentFailures"] == 1
    document = merged["projects"][0]["documents"][0]
    host_step = document["afterAll"][-1]
    assert host_step["node"] == "runner:host-result"
    assert host_step["status"] == "failed"
    assert host_step["error"]["name"] == "HostTestError"
    assert merged["diagnostics"][-1]["code"] == "run-infrastructure-error"


def test_merge_test_run_report_dumps_wraps_agent_report():
    from midscene.core.test_runner.reporting.merge_report import (
        merge_test_run_report_dumps,
    )
    from midscene.core.test_runner.reporting.metrics import (
        sum_test_run_report_metrics,
    )

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


def test_merge_test_run_report_dumps_rejects_invalid_timestamps():
    from midscene.core.test_runner.reporting.merge_report import (
        merge_test_run_report_dumps,
    )

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


def test_compile_legacy_flow_items():
    from midscene.core.device import DeviceAction
    from midscene.core.yaml.test_runner_compat import compile_legacy_flow_item

    tap = compile_legacy_flow_item({"aiTap": "submit", "name": "tapResult"})
    assert tap["node"] == "aiTap"
    assert tap["input"] == {"prompt": "submit", "options": {}}
    assert tap["meta"] == {"continueOnError": False}

    act = compile_legacy_flow_item({"ai": {"prompt": "do it"}, "cacheable": False})
    assert act["node"] == "aiAct"
    assert act["input"]["prompt"] == {"prompt": "do it"}
    assert act["input"]["options"] == {"cacheable": False}

    assertion = compile_legacy_flow_item({"aiAssert": "works", "errorMessage": "nope"})
    assert assertion["node"] == "aiAssert"
    assert assertion["input"]["options"]["keepRawResponse"] is True
    assert assertion["input"]["message"] == "nope"

    assert compile_legacy_flow_item({"sleep": 0})["node"] == "legacyValidationError"
    assert compile_legacy_flow_item({"sleep": "abc"})["node"] == "legacyValidationError"
    assert compile_legacy_flow_item({"sleep": "12"})["input"] == {"ms": 12}

    unknown = compile_legacy_flow_item({"somethingNew": True})
    assert unknown["node"] == "legacyAction"
    assert unknown["input"]["flow"] == {"somethingNew": True}

    launch = compile_legacy_flow_item(
        {"launch": "com.example.app"},
        [DeviceAction(name="Launch", description="", interface_alias="launch")],
    )
    assert launch["node"] == "action"
    assert launch["input"] == {"name": "Launch", "params": {"uri": "com.example.app"}}


def test_compile_legacy_ai_input_and_document():
    from midscene.core.yaml.test_runner_compat import (
        collect_legacy_yaml_document,
        compile_legacy_flow_item,
    )

    item = compile_legacy_flow_item(
        {"aiInput": "hello", "locate": "the name field", "name": "value"}
    )
    assert item["node"] == "action"
    assert item["input"]["name"] == "Input"
    params = item["input"]["params"]
    assert params["value"] == "hello"
    assert params["locate"]["prompt"] == "the name field"

    document = collect_legacy_yaml_document(
        {
            "tasks": [
                {"name": "first", "flow": [{"aiTap": "a"}]},
                {"name": "second", "continueOnError": True, "flow": []},
                {"name": "third"},
            ]
        },
        "/tmp/legacy.yaml",
    )
    assert document["documentId"] == "legacy-yaml:/tmp/legacy.yaml"
    assert document["projectId"] == "legacy-yaml"
    assert [case["caseIndex"] for case in document["cases"]] == [0, 1, 2]
    assert document["cases"][0]["caseId"] == (
        "legacy-yaml:/tmp/legacy.yaml:task:0"
    )
    assert document["cases"][0]["definition"]["onFailure"] == "stop-document"
    assert document["cases"][1]["definition"]["onFailure"] == "continue"
    assert document["cases"][2]["definition"]["steps"][0]["node"] == (
        "legacyValidationError"
    )


def test_create_legacy_yaml_execution_record():
    import datetime

    from midscene.core.yaml.legacy_yaml_execution_record import (
        create_legacy_yaml_execution_record,
    )

    started = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    ended = started + datetime.timedelta(seconds=1, milliseconds=500)
    options = {
        "runId": "run-1",
        "attemptIndex": 0,
        "projectName": "Project One",
        "script": {"android": {}},
        "document": _document([_step(prompt="hi")]),
        "startedAt": started,
        "endedAt": ended,
        "cleanupErrors": [RuntimeError("teardown failed")],
        "aborted": False,
        "publicationErrors": [],
        "outputs": {"answer": 42},
        "reportFile": "/tmp/report.html",
    }
    record = create_legacy_yaml_execution_record(options)
    assert record["platform"] == "android"
    assert record["status"] == "failed"
    assert record["startedAt"] == "2026-01-01T00:00:00.000Z"
    assert record["endedAt"] == "2026-01-01T00:00:01.500Z"
    assert record["durationMs"] == 1500
    assert record["reportPaths"] == ["/tmp/report.html"]
    assert record["outputs"] == {"answer": 42}
    assert "publicationErrors" not in record

    success = create_legacy_yaml_execution_record(
        {**options, "script": {}, "cleanupErrors": [], "reportFile": None}
    )
    assert success["platform"] == "web"
    assert success["status"] == "success"
    assert success["reportPaths"] == []


def test_calculate_test_run_health_classifies_retries():
    from midscene.core.test_run_health import (
        calculate_test_run_health,
        classify_test_run_case,
    )

    assert classify_test_run_case({"status": "not-run"}) == "not-run"
    assert classify_test_run_case({"status": "failed"}) == "failed"
    assert classify_test_run_case({"status": "success"}) == "passed"
    assert (
        classify_test_run_case(
            {"status": "success", "attempts": [{"attemptIndex": 0, "status": "failed"}]}
        )
        == "retry-passed"
    )
    assert (
        classify_test_run_case({"status": "success", "retryCount": 1}) == "retry-passed"
    )

    health = calculate_test_run_health(
        [
            {"status": "success"},
            {"status": "success", "run": {"attemptIndex": 1, "status": "success"}},
            {"status": "failed"},
            {"status": "not-run"},
        ]
    )
    assert health == {
        "total": 4,
        "executed": 3,
        "passed": 2,
        "failed": 1,
        "notRun": 1,
        "firstPassed": 1,
        "passedAfterRetry": 1,
        "finalPassRate": 2 / 3,
        "firstPassRate": 1 / 3,
    }


def test_build_agent_test_run_report_dump_indexes_executions():
    from midscene.core.test_runner.reporting.agent_report import (
        build_agent_test_run_report_dump,
    )

    report = _report_input()
    document = report["projects"][0]["documents"][0]
    document["reportScopeId"] = "scope-1"
    document["beforeAll"] = [
        _report_step(
            phase="beforeAll",
            report={"traces": [{"executionId": "exec-1"}]},
        )
    ]
    dump = build_agent_test_run_report_dump(
        report,
        {"executions": [{"id": "exec-1"}, {"id": None}]},
        {
            "scopeId": "scope-1",
            "reportId": "report-1",
            "sourcePath": "/tmp/agent.json",
        },
    )
    step = dump["projects"][0]["documents"][0]["beforeAll"][0]
    assert step["agentDetails"] == [{"reportId": "report-1", "executionId": "exec-1"}]
    assert dump["metrics"]["collection"]["capturedExecutionCount"] == 1
    assert "diagnostics" not in dump


def test_build_test_run_report_dump_requires_document_run_id():
    from midscene.core.test_runner.reporting.test_run_report import (
        build_test_run_report_dump,
    )

    report = _report_input()
    project = report["projects"][0]
    first = project["documents"][0]
    project["documents"] = [first, dict(first, documentRunId="doc-run-2", attemptIndex=1)]
    project["cases"][0].pop("documentRunId")
    with pytest.raises(ValueError):
        build_test_run_report_dump(
            report, {"sources": [], "metrics": {}, "diagnostics": []}
        )
