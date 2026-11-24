"""Synced from upstream packages/core/tests/unit-test/runner-resource-cleanup.test.ts.

Only the Project runtime lifecycle case represented by the aggregate suite is
synced here; the deferred-resource cases use fake timers and a quarantined
resource lifecycle that the former suite did not cover.
"""

import asyncio

import pytest

from midscene.core.test_runner.engine.project_runtime import create_project_runtime


@pytest.mark.asyncio
async def test_concurrent_finish_calls_share_one_document_and_project_cleanup():
    order: list[str] = []

    async def setup(ctx):
        order.append("setup")

        def teardown(_teardown_ctx):
            order.append("teardown")

        ctx["onTeardown"](teardown)
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

    first = runtime.finish()
    second = runtime.finish()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result is second_result
    assert first_result["status"] == "success"
    assert order == ["setup", "teardown"]
