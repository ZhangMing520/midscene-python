"""Synced from upstream ``packages/core/tests/unit-test/utils.test.ts``.

Upstream exposes coordinate helpers under the ``shrunkShotToLogicalRatio``
describe block (``scales an existing center independently from the retained
rect``).  The Python port performs the inverse conversion, from model/shot
space back to logical viewport space, in ``Agent._to_logical_coords``.
"""

import pytest


def _agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config))


class TestShrunkShotToLogicalRatio:
    def test_scales_an_existing_center_independently_from_the_retained_rect(self):
        from midscene.core.types import NodeType, Rect, Size, UIContext, UINode, UITree

        context = UIContext(
            screenshot_base64="",
            size=Size(width=320, height=240),
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
            shrunk_shot_to_logical_ratio=2.0,
        )
        element = {
            "center": (200, 240),
            "rect": {"left": 160, "top": 200, "width": 40, "height": 40},
        }
        scaled = _agent()._to_logical_coords(element, context)
        assert scaled["center"] == [100, 120]
        assert scaled["rect"]["left"] == 80


class TestAgentUtils:
    def test_get_midscene_version_returns_built_package_version(self):
        from midscene.core.agent.utils import get_midscene_version

        assert get_midscene_version() == "0.2.0"

    def test_normalizes_legacy_scroll_types(self):
        from midscene.core.agent.utils import normalize_scroll_type

        assert normalize_scroll_type("once") == "singleAction"
        assert normalize_scroll_type("untilBottom") == "scrollToBottom"
        assert normalize_scroll_type("untilTop") == "scrollToTop"
        assert normalize_scroll_type("untilRight") == "scrollToRight"
        assert normalize_scroll_type("untilLeft") == "scrollToLeft"
        assert normalize_scroll_type("singleAction") == "singleAction"
        assert normalize_scroll_type(None) is None

    def test_parses_string_and_multimodal_prompts(self):
        from midscene.core.agent.utils import parse_prompt

        assert parse_prompt("hello") == {
            "textPrompt": "hello",
            "multimodalPrompt": None,
        }
        parsed = parse_prompt(
            {"prompt": "find it", "images": [{"name": "a.png", "url": "u"}]}
        )
        assert parsed["textPrompt"] == "find it"
        assert parsed["multimodalPrompt"] == {
            "images": [{"name": "a.png", "url": "u"}],
            "convertHttpImage2Base64": False,
        }

    def test_detects_a_located_pixel_result(self):
        from midscene.core.agent.utils import (
            if_locate_param_has_located_pixel_result,
        )

        assert if_locate_param_has_located_pixel_result(
            {"locatedPixelResult": {"center": [10, 20]}}
        )
        assert not if_locate_param_has_located_pixel_result(
            {"locatedPixelResult": {"center": [10, float("nan")]}}
        )
        assert not if_locate_param_has_located_pixel_result({})
        assert not if_locate_param_has_located_pixel_result(None)

    def test_matches_an_element_from_the_plan(self):
        from midscene.core.agent.utils import match_element_from_plan

        element = match_element_from_plan(
            {
                "prompt": {"prompt": "button"},
                "locatedPixelResult": {
                    "center": [10, 20],
                    "rect": {"left": 0, "top": 0, "width": 20, "height": 40},
                },
            }
        )
        assert element["center"] == [10, 20]
        assert element["description"] == "button"
        assert element["rect"]["width"] == 20

    @pytest.mark.asyncio
    async def test_matches_an_element_from_the_cache(self):
        from midscene.core.agent.utils import match_element_from_cache

        class _Cache:
            is_cache_result_used = True

        class _Interface:
            async def rect_matches_cache_feature(self, _feature):
                return {"left": 10, "top": 20, "width": 20, "height": 40}

        element = await match_element_from_cache(
            {"taskCache": _Cache(), "interfaceInstance": _Interface()},
            {"feature": "x"},
            {"prompt": "cached"},
        )
        assert element["center"] == [20, 40]
        assert element["description"] == "cached"

    @pytest.mark.asyncio
    async def test_skips_cache_when_the_interface_has_no_feature_matcher(self):
        from midscene.core.agent.utils import match_element_from_cache

        class _Cache:
            is_cache_result_used = True

        assert (
            await match_element_from_cache(
                {"taskCache": _Cache(), "interfaceInstance": object()},
                {"feature": "x"},
                "cached",
            )
            is None
        )

    def test_transforms_a_logical_rect_to_screenshot_space(self):
        from midscene.core.agent.utils import (
            transform_logical_rect_to_screenshot_rect,
        )

        rect = {"left": 10, "top": 20, "width": 30, "height": 40}
        assert transform_logical_rect_to_screenshot_rect(rect, 1) is rect
        assert transform_logical_rect_to_screenshot_rect(rect, 2) == {
            "left": 20,
            "top": 40,
            "width": 60,
            "height": 80,
        }

    def test_transforms_a_logical_element_to_screenshot_space(self):
        from midscene.core.agent.utils import (
            transform_logical_element_to_screenshot,
        )

        element = {
            "center": [5, 10],
            "rect": {"left": 0, "top": 0, "width": 10, "height": 20},
        }
        assert transform_logical_element_to_screenshot(element, 1) is element
        scaled = transform_logical_element_to_screenshot(element, 3)
        assert scaled["center"] == [15, 30]
        assert scaled["rect"] == {
            "left": 0,
            "top": 0,
            "width": 30,
            "height": 60,
        }

    @pytest.mark.asyncio
    async def test_creates_a_screenshot_bound_ui_context(self):
        from midscene.core.agent.utils import (
            create_screenshot_bound_ui_context,
        )
        from tests.core_helpers import make_png_base64

        context = await create_screenshot_bound_ui_context(
            make_png_base64(120, 80),
            {"screenshotSize": {"width": 120, "height": 80}},
        )
        assert context.shrunk_shot_to_logical_ratio == 1
        assert (context.size.width, context.size.height) == (120, 80)
        assert context.screenshot_base64.startswith("data:image/png;base64,")

    def test_prints_the_report_message_unless_quiet(self, monkeypatch):
        from midscene.core.agent import utils

        messages = []
        monkeypatch.setattr(utils, "log_report", messages.append)

        class _Config:
            def __init__(self, quiet):
                self.quiet = quiet

            def get_env_config_in_boolean(self, _key):
                return self.quiet

        monkeypatch.setattr(
            utils, "get_global_config_manager", lambda: _Config(True)
        )
        utils.print_report_msg("report.html")
        assert messages == []

        monkeypatch.setattr(
            utils, "get_global_config_manager", lambda: _Config(False)
        )
        utils.print_report_msg("report.html")
        assert messages == ["Midscene - report file updated: report.html"]
