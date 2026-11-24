"""Synced from upstream packages/core/tests/unit-test/runner-field-mapping.test.ts.

Covers the shared workflow field semantics cases represented by the former
aggregate suite: per-Step data across lifecycle/retry and stop-document
handling.
"""

from typing import Any

import pytest

from midscene.core.test_runner.engine.run_workflow_document import (
    run_workflow_document,
)
from midscene.core.test_runner.errors import NodeExecutionError
from midscene.core.test_runner.node.define_node import define_node


def _step(node: str) -> dict[str, Any]:
    return {"node": node, "input": {}, "meta": {"continueOnError": False}}


def _document() -> dict[str, Any]:
    return {
        "documentId": "document",
        "projectId": "project",
        "sourcePath": "flow.yaml",
        "lifecycle": {
            "beforeAll": [],
            "beforeEach": [],
            "afterEach": [],
            "afterAll": [],
        },
        "cases": [],
    }


def _add_case(
    document: dict[str, Any],
    name: str,
    steps: list[dict[str, Any]],
    on_failure: str = None,
) -> None:
    definition: dict[str, Any] = {"name": name, "steps": steps}
    if on_failure:
        definition["onFailure"] = on_failure
    document["cases"].append(
        {
            "caseId": name,
            "projectId": document["projectId"],
            "sourcePath": document["sourcePath"],
            "caseIndex": len(document["cases"]),
            "definition": definition,
        }
    )


@pytest.mark.asyncio
async def test_keeps_data_per_step_across_lifecycle_and_retry_attempts_without_named_aggregation():
    document = _document()
    document["lifecycle"]["beforeAll"] = [_step("phase")]
    document["lifecycle"]["beforeEach"] = [_step("phase")]
    document["lifecycle"]["afterEach"] = [_step("phase")]
    document["lifecycle"]["afterAll"] = [_step("phase")]
    _add_case(document, "retry", [_step("value"), _step("flaky")])

    observed: dict[str, Any] = {}

    def on_document_result(result):
        observed["value"] = result["afterAll"][0]["output"]["data"]

    def resolve_node(name):
        async def execute(ctx):
            if name == "phase":
                phase = (
                    ctx.case["phase"] if ctx.scope == "case" else ctx.document["phase"]
                )
                return {"data": {"value": phase}}
            if name == "value":
                attempt = ctx.case["attemptIndex"] if ctx.scope == "case" else -1
                return {"data": {"a/b": {"~key": [attempt]}}}
            if ctx.scope == "case" and ctx.case["attemptIndex"] == 0:
                raise NodeExecutionError(
                    name, RuntimeError("retry"), {"data": {"reason": "temporary"}}
                )
            return None

        return define_node(name, execute)

    result = await run_workflow_document(
        document,
        {
            "retry": 1,
            "onDocumentResult": on_document_result,
            "resolveNode": resolve_node,
        },
    )
    assert "outputs" not in result["document"]
    assert observed["value"] == {"value": "afterAll"}
    assert result["cases"][0]["attempts"][0]["steps"][0]["output"]["data"] == {
        "a/b": {"~key": [0]}
    }
    assert result["cases"][0]["attempts"][1]["steps"][0]["output"]["data"] == {
        "a/b": {"~key": [1]}
    }
    assert result["cases"][0]["attempts"][0]["steps"][1]["output"]["data"] == {
        "reason": "temporary"
    }


@pytest.mark.asyncio
async def test_stops_only_the_document_after_a_stop_document_case_and_still_runs_cleanup():
    document = _document()
    _add_case(document, "allowed", [_step("fail"), _step("skipped")])
    _add_case(document, "stop", [_step("fail")], "stop-document")
    _add_case(document, "later", [_step("skipped")])
    document["lifecycle"]["afterAll"] = [_step("cleanup")]
    calls: list[str] = []

    def resolve_node(name):
        async def execute(ctx):
            calls.append(name)
            if name == "fail":
                raise RuntimeError("business failure")

        return define_node(name, execute)

    result = await run_workflow_document(document, {"resolveNode": resolve_node})
    assert [case["status"] for case in result["cases"]] == [
        "failed",
        "failed",
        "not-run",
    ]
    assert calls == ["fail", "fail", "cleanup"]
