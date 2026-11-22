"""Synced from upstream packages/cli/tests/unit-test/process-cache-config.test.ts."""

from midscene.core.utils import process_cache_config


def test_should_return_cache_object_with_id_when_cache_config_is_provided_with_id():
    cache_config = {"id": "test-cache-id", "strategy": "read-write"}

    assert process_cache_config(cache_config, "fallback-id") == {
        "id": "test-cache-id",
        "strategy": "read-write",
    }


def test_should_auto_generate_id_when_cache_config_is_true():
    assert process_cache_config(True, "fallback-id") == {"id": "fallback-id"}


def test_should_auto_generate_id_when_cache_config_object_has_no_id():
    assert process_cache_config({"strategy": "read-only"}, "fallback-id") == {
        "id": "fallback-id",
        "strategy": "read-only",
    }


def test_should_preserve_explicit_false_when_cache_config_is_false():
    assert process_cache_config(False, "fallback-id") is False


def test_should_return_undefined_when_cache_config_is_undefined():
    assert process_cache_config(None, "fallback-id") is None
