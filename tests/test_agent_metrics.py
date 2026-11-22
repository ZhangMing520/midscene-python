"""Synced from upstream ``packages/core/tests/unit-test/agent-metrics.test.ts``
(``collects usage reported through the model runtime onUsage callback``)."""

from typing import Any, Dict, List


def _agent(on_llm_usage):
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
        AgentOptions(model_config=config, on_llm_usage=on_llm_usage),
    )


def test_collects_usage_reported_through_the_model_runtime_on_usage_callback():
    usages: List[Dict[str, Any]] = []
    agent = _agent(on_llm_usage=usages.append)
    runtime = agent.model_runtime("planning")
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    runtime.on_usage(usage)
    assert usages == [usage]
    agent._record_usage_metrics("planning", usage)
    assert agent.metrics["planning"]["total_tokens"] == 15
