"""Synced from upstream ``packages/core/tests/unit-test/agent-metrics.test.ts``
(``collects usage reported through the model runtime onUsage callback``)."""

from typing import Any


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


def _usage(**overrides):
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_input": 0,
        "time_cost": 0,
        "model_name": None,
        "intent": None,
    }
    usage.update(overrides)
    return usage


class TestMetricsCollector:
    def test_aggregates_totals_and_breaks_down_by_intent_and_model(self):
        from midscene.core.agent.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.add(
            _usage(
                prompt_tokens=100,
                completion_tokens=40,
                total_tokens=140,
                cached_input=10,
                time_cost=500,
                intent="planning",
                model_name="model-a",
            )
        )
        collector.add(
            _usage(
                prompt_tokens=60,
                completion_tokens=20,
                total_tokens=80,
                cached_input=5,
                time_cost=300,
                intent="insight",
                model_name="model-a",
            )
        )

        snapshot = collector.snapshot()
        assert snapshot["totalPromptTokens"] == 160
        assert snapshot["totalCompletionTokens"] == 60
        assert snapshot["totalTokens"] == 220
        assert snapshot["totalCachedInput"] == 15
        assert snapshot["totalTimeCostMs"] == 800
        assert snapshot["calls"] == 2
        assert snapshot["byIntent"]["planning"] == {
            "promptTokens": 100,
            "completionTokens": 40,
            "totalTokens": 140,
            "calls": 1,
        }
        assert snapshot["byIntent"]["insight"]["calls"] == 1
        assert snapshot["byModel"]["model-a"] == {
            "promptTokens": 160,
            "completionTokens": 60,
            "totalTokens": 220,
            "calls": 2,
        }

    def test_treats_missing_token_fields_as_zero_and_missing_labels_as_unknown(self):
        from midscene.core.agent.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.add(_usage())
        snapshot = collector.snapshot()
        assert snapshot["totalTokens"] == 0
        assert snapshot["calls"] == 1
        assert snapshot["byIntent"]["unknown"]["calls"] == 1
        assert snapshot["byModel"]["unknown"]["calls"] == 1

    def test_returns_an_independent_snapshot(self):
        from midscene.core.agent.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.add(_usage(total_tokens=10, intent="planning"))
        first = collector.snapshot()
        collector.add(_usage(total_tokens=10, intent="planning"))
        assert first["totalTokens"] == 10
        assert first["byIntent"]["planning"]["calls"] == 1


def test_collects_usage_reported_through_the_model_runtime_on_usage_callback():
    usages: list[dict[str, Any]] = []
    agent = _agent(on_llm_usage=usages.append)
    runtime = agent.model_runtime("planning")
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    runtime.on_usage(usage)
    assert usages == [usage]
    agent._record_usage_metrics("planning", usage)
    assert agent.metrics["planning"]["total_tokens"] == 15
