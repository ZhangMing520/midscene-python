"""Synced from upstream
``packages/web-integration/tests/unit-test/viewport.test.ts``.
"""

import re

import pytest

from midscene.web_integration.common.viewport import (
    DEFAULT_PUPPETEER_WINDOW_VIEWPORT_SIZE,
    DEFAULT_STATIC_PAGE_VIEWPORT_SIZE,
    DEFAULT_VIEWPORT_SIZE,
    resolve_viewport_size,
    resolve_web_viewport_size,
)


def test_uses_the_shared_default_viewport_size():
    """uses the shared default viewport size"""
    assert DEFAULT_VIEWPORT_SIZE == {"width": 1440, "height": 800}
    assert DEFAULT_PUPPETEER_WINDOW_VIEWPORT_SIZE == {"width": 1440, "height": 800}
    assert DEFAULT_STATIC_PAGE_VIEWPORT_SIZE == {"width": 1440, "height": 800}


def test_falls_back_to_default_or_provided_fallback_for_missing_dimensions():
    """falls back to default or provided fallback for missing dimensions"""
    assert resolve_viewport_size() == DEFAULT_VIEWPORT_SIZE
    assert resolve_viewport_size(
        {"width": None, "height": "720"},
        {"width": 1280, "height": 800},
    ) == {"width": 1280, "height": 720}


def test_resolves_viewport_and_web_viewport_values_from_numbers_or_strings():
    """resolves viewport and web viewport values from numbers or strings"""
    assert resolve_viewport_size({"width": "1536", "height": 864}) == {
        "width": 1536,
        "height": 864,
    }
    assert resolve_web_viewport_size(
        {"viewportWidth": 1600, "viewportHeight": "900"}
    ) == {"width": 1600, "height": 900}


def test_rejects_non_positive_fractional_or_malformed_dimensions():
    """rejects non-positive, fractional, or malformed dimensions"""
    with pytest.raises(
        ValueError,
        match=re.escape("viewportWidth must be greater than 0, but got 0"),
    ):
        resolve_viewport_size({"width": 0})
    with pytest.raises(
        ValueError,
        match=re.escape("viewportHeight must be greater than 0, but got -1"),
    ):
        resolve_viewport_size({"height": -1})
    with pytest.raises(
        ValueError,
        match=re.escape(
            "viewportWidth must be a positive integer, but got 1280.5"
        ),
    ):
        resolve_viewport_size({"width": 1280.5})
    with pytest.raises(
        ValueError,
        match=re.escape(
            "viewportHeight must be a positive integer, but got 720px"
        ),
    ):
        resolve_viewport_size({"height": "720px"})
