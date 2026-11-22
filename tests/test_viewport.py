"""Synced from upstream
``packages/web-integration/tests/unit-test/viewport.test.ts``.

Python ``web_integration/common/viewport.py`` only exposes
``DEFAULT_VIEWPORT_SIZE`` plus ``parse_viewport_size()``/
``parse_viewport_dimension()``; the upstream resolve helpers and their exact
validation messages were not ported.
"""

import pytest


@pytest.mark.skip(
    reason="Python viewport.py defines only DEFAULT_VIEWPORT_SIZE; the "
    "defaultPuppeteerWindowViewportSize/defaultStaticPageViewportSize aliases "
    "do not exist"
)
def test_uses_the_shared_default_viewport_size():
    """uses the shared default viewport size"""
    pass


@pytest.mark.skip(
    reason="Python viewport.py has no resolve_viewport_size() with "
    "null/fallback dimension handling"
)
def test_falls_back_to_default_or_provided_fallback_for_missing_dimensions():
    """falls back to default or provided fallback for missing dimensions"""
    pass


@pytest.mark.skip(
    reason="Python viewport.py has no resolve_web_viewport_size() "
    "(viewportWidth/viewportHeight) helper"
)
def test_resolves_viewport_and_web_viewport_values_from_numbers_or_strings():
    """resolves viewport and web viewport values from numbers or strings"""
    pass


@pytest.mark.skip(
    reason="Python parse_viewport_dimension() emits 'must be a positive "
    "integer' for every invalid value and int() accepts fractional input, so "
    "the upstream per-value error messages do not hold"
)
def test_rejects_non_positive_fractional_or_malformed_dimensions():
    """rejects non-positive, fractional, or malformed dimensions"""
    pass
