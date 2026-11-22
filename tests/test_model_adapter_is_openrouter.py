"""Synced from upstream packages/core/tests/unit-test/model-adapter/is-openrouter.test.ts."""

import pytest

from midscene.core.ai_model.model_adapter.is_openrouter import _is_openrouter


def test_recognizes_the_supported_endpoint():
    """recognizes the supported endpoint"""
    assert _is_openrouter("https://openrouter.ai/api/v1") is True


@pytest.mark.parametrize(
    "base_url",
    [
        None,
        "",
        "http://openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1/",
        "https://openrouter.ai/api/v2",
        "https://openrouter.ai",
        "https://proxy.example.com/api/v1",
    ],
    ids=[
        "undefined",
        "empty",
        "http-scheme",
        "trailing-slash",
        "v2",
        "host-only",
        "proxy",
    ],
)
def test_does_not_apply_openrouter_mappings_for(base_url):
    """does not apply OpenRouter mappings for %s"""
    assert _is_openrouter(base_url) is False
