"""Synced from upstream ``packages/core/tests/unit-test/agent-cache-config.test.ts``."""

import pytest

from midscene.core.agent.cache_config import (
    normalize_agent_cache_config,
    validate_agent_cache_input,
)


class TestValidateAgentCacheInput:
    def test_accepts_disabled_or_valid_cache_config(self):
        validate_agent_cache_input(None)
        validate_agent_cache_input(False)
        validate_agent_cache_input(
            {
                "id": "custom-cache-id",
                "strategy": "read-write",
                "cacheDir": "./cache",
            }
        )

    def test_rejects_cache_true_because_agent_requires_explicit_cache_id(self):
        with pytest.raises(
            ValueError, match="cache: true requires an explicit cache ID"
        ):
            validate_agent_cache_input(True)

    def test_rejects_cache_object_without_explicit_id(self):
        with pytest.raises(
            ValueError,
            match="cache configuration requires an explicit id",
        ):
            validate_agent_cache_input({"strategy": "read-only"})

    def test_rejects_empty_cache_dir(self):
        with pytest.raises(
            ValueError,
            match="cache.cacheDir must be a non-empty string when provided",
        ):
            validate_agent_cache_input({"id": "custom-cache-id", "cacheDir": "  "})

    def test_rejects_non_string_strategy(self):
        with pytest.raises(
            ValueError,
            match="cache.strategy must be a string when provided",
        ):
            validate_agent_cache_input({"id": "custom-cache-id", "strategy": 1})

    def test_rejects_unsupported_strategy(self):
        with pytest.raises(
            ValueError,
            match='cache.strategy must be one of "read-only", "read-write", '
            '"write-only"',
        ):
            validate_agent_cache_input({"id": "custom-cache-id", "strategy": "invalid"})


class TestNormalizeAgentCacheConfig:
    @pytest.mark.parametrize("strategy", ["read-only", "read-write", "write-only"])
    def test_preserves_cache_normalization(self, strategy):
        original = {
            "cache": {
                "id": "cache-id",
                "strategy": strategy,
                "cacheDir": "  ./cache  ",
            }
        }
        assert normalize_agent_cache_config(original) == {
            "id": "cache-id",
            "enabled": strategy != "write-only",
            "readOnly": strategy == "read-only",
            "writeOnly": strategy == "write-only",
            "cacheDir": "./cache",
        }
        assert original["cache"]["cacheDir"] == "  ./cache  "

    def test_retains_disabled_cache_behavior(self):
        assert normalize_agent_cache_config({"cache": False}) is None

    def test_accepts_a_cache_id_string(self):
        assert normalize_agent_cache_config({"cache": "my-cache"}) == {
            "id": "my-cache",
            "enabled": True,
            "readOnly": False,
            "writeOnly": False,
            "cacheDir": None,
        }
