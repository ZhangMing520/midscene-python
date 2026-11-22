"""Synced from upstream packages/core/tests/unit-test/runner-execution-failure.test.ts."""

import pytest

from midscene.core.test_runner.engine.execution_failure import WorkflowExecutionFailure
from midscene.core.test_runner.engine.run_collected_case import run_collected_case
from midscene.core.test_runner.node.define_node import define_node
from midscene.core.yaml.test_runner_compat import collect_legacy_yaml_document


def _document():
    return collect_legacy_yaml_document(
        {
            "tasks": [
                {"name": "first", "flow": [{"javascript": "first()"}]},
                {"name": "second", "flow": [{"javascript": "second()"}]},
            ]
        }
    )


def _resolve_node():
    async def execute(ctx):
        def cleanup():
            raise RuntimeError("cleanup failed")

        ctx.on_teardown(cleanup)
        return {"data": 42}

    return define_node("javascript", execute)


@pytest.mark.asyncio
async def test_retains_a_completed_step_and_cleanup_errors_when_its_callback_throws():
    def on_step_result(_info, _result):
        raise RuntimeError("callback failed")

    with pytest.raises(WorkflowExecutionFailure) as raised:
        await run_collected_case(
            _document()["cases"][0],
            {"resolveNode": lambda _name: _resolve_node(), "onStepResult": on_step_result},
        )
    failure = raised.value
    assert failure.result["status"] == "failed"
    assert failure.result["steps"][0]["status"] == "success"
    assert failure.result["steps"][0]["output"]["data"] == 42
    assert failure.result["executionStatus"] == "success"
    assert "callback failed" in str(failure.result["executionErrors"][0])
    assert "cleanup failed" in str(failure.result["teardownErrors"][0])
