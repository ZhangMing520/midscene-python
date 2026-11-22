"""Synced from upstream packages/core/tests/unit-test/screenshot-preparation.test.ts."""

import base64
import io

import pytest

from midscene.core.agent.screenshot_preparation import (
    prepare_raw_screenshot,
    prepare_screenshot_for_persistence,
)


def _image_base64(width: int = 320, height: int = 240, fmt: str = "PNG") -> str:
    from PIL import Image

    image = Image.new("RGB", (width, height), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return "data:image/{};base64,{}".format(
        fmt.lower(),
        base64.b64encode(buffer.getvalue()).decode("ascii"),
    )


def _image_size(data_url: str):
    from PIL import Image

    raw = data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(raw))).size


def _image_format(data_url: str) -> str:
    return data_url.split(";", 1)[0].split("/", 1)[1]


@pytest.mark.asyncio
async def test_normalizes_a_png_to_jpeg_without_changing_its_dimensions():
    """normalizes a PNG to JPEG without changing its dimensions"""
    result = await prepare_raw_screenshot(_image_base64(), {})
    assert result["base64"].startswith("data:image/jpeg;base64,")
    assert result["originalSize"] == {"width": 320, "height": 240}
    assert result["shotSize"] == {"width": 320, "height": 240}
    assert _image_size(result["base64"]) == (320, 240)


@pytest.mark.asyncio
async def test_applies_the_shrink_factor_once_and_returns_the_prepared_dimensions():
    """applies the shrink factor once and returns the prepared dimensions"""
    result = await prepare_raw_screenshot(_image_base64(), {"shrinkFactor": 2})
    assert result["originalSize"] == {"width": 320, "height": 240}
    assert result["shotSize"] == {"width": 160, "height": 120}
    assert _image_size(result["base64"]) == (160, 120)


@pytest.mark.asyncio
async def test_keeps_jpeg_dimensions_while_preserving_the_jpeg_output_contract():
    """keeps JPEG dimensions while preserving the JPEG output contract"""
    source = _image_base64(640, 480, fmt="JPEG")
    result = await prepare_raw_screenshot(source, {"shrinkFactor": 1})
    assert result["base64"] == source
    assert _image_format(result["base64"]) == "jpeg"
    assert _image_size(result["base64"]) == (640, 480)


@pytest.mark.asyncio
@pytest.mark.parametrize("shrink_factor", [0, 0.5, float("nan"), float("inf")])
async def test_rejects_invalid_shrink_factor(shrink_factor):
    """rejects invalid shrink factor %s"""
    with pytest.raises(ValueError):
        await prepare_raw_screenshot(_image_base64(), {"shrinkFactor": shrink_factor})


@pytest.mark.asyncio
async def test_rejects_a_shrink_factor_that_rounds_the_target_size_to_zero():
    """rejects a shrink factor that rounds the target size to zero"""
    with pytest.raises(ValueError):
        await prepare_raw_screenshot(_image_base64(1, 1), {"shrinkFactor": 100})


@pytest.mark.asyncio
async def test_prepare_screenshot_for_persistence_converts_unscaled_png_to_jpeg():
    """prepareScreenshotForPersistence normalizes unscaled screenshots to JPEG"""
    result = await prepare_screenshot_for_persistence(_image_base64(), {})
    assert result.startswith("data:image/jpeg;base64,")
    assert _image_size(result) == (320, 240)
