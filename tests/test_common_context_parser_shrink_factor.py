"""Synced from upstream
``packages/core/tests/unit-test/common-context-parser-shrink-factor.test.ts``.

The Python agent keeps the same shrink contract: the saved screenshot is
resized by ``screenshotShrinkFactor`` and ``shrunkShotToLogicalRatio`` records
the model-image to logical-viewport ratio used by later locate scaling.
"""

import base64
import io

import pytest

from tests.core_helpers import MockInterface, make_png_base64


def _agent(model_family: str = "gpt-5", **options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": model_family,
    }
    return Agent(MockInterface(), AgentOptions(model_config=config, **options))


def _context(width: int, height: int, logical_width: int, logical_height: int):
    from midscene.core.types import NodeType, Rect, Size, UIContext, UINode, UITree

    return UIContext(
        screenshot_base64=make_png_base64(width, height),
        size=Size(width=logical_width, height=logical_height),
        content=[],
        tree=UITree(
            node=UINode(
                id="root",
                content="",
                rect=Rect(left=0, top=0, width=0, height=0),
                center=(0, 0),
                node_type=NodeType.CONTAINER,
            )
        ),
    )


def _image_size(base64_str: str):
    from PIL import Image

    raw = (
        base64_str.split(",", 1)[1]
        if base64_str.startswith("data:")
        else base64_str
    )
    return Image.open(io.BytesIO(base64.b64decode(raw))).size


class TestCommonContextParserShrinkFactor:
    def test_uses_screenshot_shrink_factor_when_configured(self):
        agent = _agent(screenshot_shrink_factor=2.0)
        shrunk = agent._apply_screenshot_shrink(_context(320, 240, 160, 120))
        assert _image_size(shrunk.screenshot_base64) == (160, 120)
        # dpr = 320/160 = 2; ratio = dpr / factor = 1
        assert shrunk.shrunk_shot_to_logical_ratio == pytest.approx(1.0)

    def test_does_not_shrink_when_screenshot_shrink_factor_is_not_provided(self):
        context = _context(320, 240, 320, 240)
        shrunk = _agent()._apply_screenshot_shrink(context)
        assert shrunk.screenshot_base64 == context.screenshot_base64
        assert shrunk.shrunk_shot_to_logical_ratio == 1.0

    def test_should_handle_dpr_2_without_screenshot_shrink_factor(self):
        """A dpr != 1 screenshot (e.g. the Chrome extension CDP capture) is
        kept as-is but the ratio is still recorded."""
        context = _context(320, 240, 160, 120)
        shrunk = _agent()._apply_screenshot_shrink(context)
        assert shrunk.screenshot_base64 == context.screenshot_base64
        assert shrunk.shrunk_shot_to_logical_ratio == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_should_handle_dpr_1_with_screenshot_shrink_factor(self):
        """get_ui_context applies shrink when the option is set."""
        agent = _agent(screenshot_shrink_factor=2.0)
        context = await agent.get_ui_context("locate")
        # logical 160x120 from MockInterface(320x240 png, size 320x240):
        # physical 320 == logical 320 -> dpr 1 -> ratio 0.5, image halved
        assert context.shrunk_shot_to_logical_ratio == pytest.approx(0.5)
        assert _image_size(context.screenshot_base64) == (160, 120)
