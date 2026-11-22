"""Synced from upstream
``packages/core/tests/unit-test/agent-action-readiness.test.ts``
(``waits after every successful action on %s``)."""

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tests.core_helpers import patch_model_call


def _agent(wait_after_action_ms: int = 0):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(
        MockInterface(),
        AgentOptions(model_config=config, wait_after_action_ms=wait_after_action_ms),
    )


@pytest.mark.asyncio
async def test_waits_after_every_successful_action_on_android():
    agent = _agent(wait_after_action_ms=0)
    sleeps: List[float] = []

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        # must yield, or the readiness task can never run
        await real_sleep(min(seconds, 0.01) if seconds else 0)

    responses = [
        (
            "<action-type>Sleep</action-type>\n<action-param-json>\n"
            '{"timeMs": 1}\n</action-param-json>'
        ),
        '<complete success="true">done</complete>',
    ]
    calls = {"n": 0}

    async def planning_handler(*args, **kwargs):
        calls["n"] += 1
        return {"content": responses[calls["n"] - 1], "usage": {"total_tokens": 3}}

    readiness_calls: List[Dict[str, Any]] = []

    async def readiness(context):
        readiness_calls.append(context)

    with patch("asyncio.sleep", new=fake_sleep), patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        planning_handler,
    ):
        agent.options.wait_for_action_ready = readiness
        await agent.ai_act("run")

    assert readiness_calls and readiness_calls[0]["action"]["name"] == "Sleep"
