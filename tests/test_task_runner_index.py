"""Synced from upstream packages/core/tests/unit-test/task-runner/index.test.ts."""

import pytest

from midscene.core.task_runner import TaskExecutionError, TaskRunner


@pytest.mark.asyncio
async def test_insight_basic_run():
    async def build_context(signal=None):
        return {"screenshot_base64": "data:image/png;base64,AAA"}

    async def executor(ctx):
        return {"thought": "ok", "output": 123}

    runner = TaskRunner("exec", build_context)
    result = await runner.append_and_flush(
        {"type": "Insight", "subType": "Query", "executor": executor}
    )

    assert result == {"thought": "ok", "output": 123}
    assert runner.status == "completed"
    dump = runner.dump()
    assert dump["tasks"][0]["status"] == "finished"
    assert dump["tasks"][0]["recorder"][0]["timing"] == "after-calling"


@pytest.mark.asyncio
async def test_insight_run_with_error():
    async def build_context(signal=None):
        return None

    async def boom(ctx):
        raise RuntimeError("kaboom")

    runner = TaskRunner("exec", build_context)
    with pytest.raises(TaskExecutionError) as raised:
        await runner.append_and_flush(
            {"type": "Insight", "subType": "Query", "executor": boom}
        )

    assert raised.value.code == "TASK_EXECUTION_FAILED"
    assert runner.status == "error"
    assert runner.latest_error_task()["errorMessage"] == "kaboom"


@pytest.mark.asyncio
async def test_insight_run_with_error_appends_error_task():
    async def build_context(signal=None):
        return None

    runner = TaskRunner("exec", build_context)
    with pytest.raises(TaskExecutionError):
        await runner.append_error_plan("plan failed")

    assert runner.tasks[0]["subType"] == "Error"
    assert runner.tasks[0]["errorMessage"] == "plan failed"
