"""Synced from upstream packages/core/tests/unit-test/screenshot-preparation.test.ts.

The Python module only ports ``get_ui_context`` / ``apply_screenshot_shrink``
(PNG shrink to a logical ratio). Upstream's ``prepareRawScreenshot`` JPEG
normalization pipeline (finite ``screenshotShrinkFactor`` validation,
``imageInfoOfBase64``, ``resizeBase64ImageToJpeg``) is not ported, so every
case in this file is kept and skipped for that specific reason.
"""

import pytest

_SKIP = pytest.mark.skip(
    reason="Python screenshot_preparation has no prepareRawScreenshot JPEG "
    "normalization pipeline; only get_ui_context/apply_screenshot_shrink exist"
)


@_SKIP
@pytest.mark.asyncio
async def test_normalizes_a_png_to_jpeg_without_changing_its_dimensions():
    """normalizes a PNG to JPEG without changing its dimensions"""
    pass


@_SKIP
@pytest.mark.asyncio
async def test_applies_the_shrink_factor_once_and_returns_the_prepared_dimensions():
    """applies the shrink factor once and returns the prepared dimensions"""
    pass


@_SKIP
@pytest.mark.asyncio
async def test_keeps_jpeg_dimensions_while_preserving_the_jpeg_output_contract():
    """keeps JPEG dimensions while preserving the JPEG output contract"""
    pass


@_SKIP
@pytest.mark.asyncio
@pytest.mark.parametrize("shrink_factor", [0, 0.5, float("nan"), float("inf")])
async def test_rejects_invalid_shrink_factor(shrink_factor):
    """rejects invalid shrink factor %s"""
    pass


@_SKIP
@pytest.mark.asyncio
async def test_rejects_a_shrink_factor_that_rounds_the_target_size_to_zero():
    """rejects a shrink factor that rounds the target size to zero"""
    pass
