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
