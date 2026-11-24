"""Synced from upstream
``packages/core/tests/unit-test/common-context-parser-shrink-factor.test.ts``
and ``common-context-parser-orientation.test.ts``.

Upstream UIContext exposes ``shotSize``/``deprecatedDpr``; the Python model
stores the model-image size in the screenshot itself and keeps the logical
viewport in ``size``, so the same contracts are asserted through those fields.
"""

import base64
import io

import pytest

from midscene.core.agent.utils import common_context_parser


def _png(width: int, height: int) -> str:
    from PIL import Image

    image = Image.new("RGB", (width, height), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def _image_size(data_url: str):
    from PIL import Image

    raw = data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(raw))).size


class _Interface:
    def __init__(self, logical, physical):
        self._logical = logical
        self._physical = physical

    async def screenshot_base64(self) -> str:
        return _png(*self._physical)

    async def size(self):
        return {"width": self._logical[0], "height": self._logical[1]}

    def describe(self) -> str:
        return ""


class TestCommonContextParserShrinkFactor:
    @pytest.mark.asyncio
    async def test_converts_png_screenshots_to_jpeg_quality_90_when_not_shrinking(self):
        context = await common_context_parser(_Interface((800, 400), (2400, 1200)), {})
        assert context.screenshot_base64.startswith("data:image/jpeg;base64,")
        assert _image_size(context.screenshot_base64) == (2400, 1200)

    @pytest.mark.asyncio
    async def test_does_not_shrink_when_screenshot_shrink_factor_is_not_provided(self):
        context = await common_context_parser(_Interface((800, 400), (2400, 1200)), {})
        assert _image_size(context.screenshot_base64) == (2400, 1200)

    @pytest.mark.asyncio
    async def test_uses_screenshot_shrink_factor_when_configured(self):
        context = await common_context_parser(
            _Interface((800, 400), (2400, 1200)),
            {"screenshotShrinkFactor": 2},
        )
        assert _image_size(context.screenshot_base64) == (1200, 600)

    @pytest.mark.asyncio
    async def test_should_handle_dpr_1_with_screenshot_shrink_factor(self):
        context = await common_context_parser(
            _Interface((1216, 2688), (1216, 2688)),
            {"screenshotShrinkFactor": 2},
        )
        assert _image_size(context.screenshot_base64) == (608, 1344)
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_should_handle_dpr_1_without_screenshot_shrink_factor(self):
        context = await common_context_parser(
            _Interface((1216, 2688), (1216, 2688)), {}
        )
        assert _image_size(context.screenshot_base64) == (1216, 2688)
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(1)


class TestCommonContextParserOrientation:
    @pytest.mark.asyncio
    async def test_should_compute_correct_dpr_for_portrait(self):
        context = await common_context_parser(_Interface((360, 720), (1080, 2160)), {})
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(3)
        assert (context.size.width, context.size.height) == (360, 720)

    @pytest.mark.asyncio
    async def test_should_compute_correct_dpr_for_landscape(self):
        context = await common_context_parser(_Interface((720, 360), (2160, 1080)), {})
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(3)

    @pytest.mark.asyncio
    async def test_should_swap_logical_dimensions_when_orientation_mismatches(self):
        context = await common_context_parser(_Interface((359, 717), (1972, 988)), {})
        expected_dpr = 1972 / 717
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(expected_dpr)
        assert context.size.width == 717
        assert context.size.height == 359

    @pytest.mark.asyncio
    async def test_should_swap_logical_dimensions_for_reverse_mismatch(self):
        context = await common_context_parser(_Interface((717, 359), (988, 1972)), {})
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(988 / 359)

    @pytest.mark.asyncio
    async def test_should_not_swap_dimensions_for_square_screenshots(self):
        context = await common_context_parser(_Interface((400, 400), (1200, 1200)), {})
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(3)

    @pytest.mark.asyncio
    async def test_should_handle_shrink_factor_with_orientation_mismatch(self):
        context = await common_context_parser(
            _Interface((359, 717), (1972, 988)),
            {"screenshotShrinkFactor": 2},
        )
        assert context.shrunk_shot_to_logical_ratio == pytest.approx((1972 / 717) / 2)
        assert _image_size(context.screenshot_base64) == (986, 494)
