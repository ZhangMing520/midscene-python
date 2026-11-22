"""Synced from upstream ``packages/core/tests/unit-test/agent-cache-config.test.ts``
and ``packages/core/tests/unit-test/agent-options.test.ts``."""

import pytest


def _agent(cache):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config, cache=cache))


class TestAgentCacheConfig:
    def test_preserves_cache_normalization_for_read_only(self, tmp_path):
        agent = _agent(
            {"id": "c1", "strategy": "read-only", "cacheDir": str(tmp_path)}
        )
        cache = agent._get_task_cache()
        assert cache.read_only_mode is True and cache.write_only_mode is False
        assert str(tmp_path) in cache.cache_file_path

    def test_preserves_cache_normalization_for_write_only(self):
        agent = _agent({"id": "c2", "strategy": "write-only"})
        cache = agent._get_task_cache()
        assert cache.write_only_mode is True

    def test_rejects_unsupported_strategy(self):
        agent = _agent({"id": "c3", "strategy": "sometimes"})
        with pytest.raises(ValueError):
            agent._get_task_cache()

    def test_retains_disabled_cache_behavior(self):
        agent = _agent(False)
        assert agent._get_task_cache() is None
