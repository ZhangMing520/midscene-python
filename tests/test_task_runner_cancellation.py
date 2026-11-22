"""Synced from upstream
``packages/core/tests/unit-test/task-runner-cancellation.test.ts``
(``preserves abort diagnostics and bounds the prefixed message``)."""

import pytest


def _agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config))


@pytest.mark.asyncio
async def test_preserves_abort_diagnostics_and_bounds_the_prefixed_message():
    from midscene.core.types import AbortError, AbortSignal

    signal = AbortSignal()
    signal.abort("user cancelled")
    with pytest.raises(
        AbortError, match="Operation interrupted by an external abort signal"
    ) as excinfo:
        await _agent().ai_act("run", {"abortSignal": signal})
    assert "Reason: user cancelled" in str(excinfo.value)
