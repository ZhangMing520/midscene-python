"""Synced from upstream packages/core/tests/unit-test/service-locate-deeplocate.test.ts."""

from typing import Any, Dict
from unittest.mock import patch

import pytest

from tests.core_helpers import MockInterface


@pytest.fixture
def mock_interface():
    return MockInterface()


def _make_runtime(**overrides):
    from midscene.core.ai_model.models.registry import get_model_runtime

    config = {
        "modelName": "mock-model",
        "intent": "locate",
        "slot": "locate",
        "modelFamily": "gpt-5",
        "retryCount": 0,
        "retryInterval": 0,
        "responseFormat": "none",
    }
    config.update(overrides)
    return get_model_runtime(config)


class TestDeepLocate:
    @pytest.mark.asyncio
    async def test_two_stage_locate(self, mock_interface):
        """deepLocate with a plan coordinate hint: search-area crop + element
        locate on the zoomed image, then mapping back."""
        from midscene.core.service import locate_service

        async def fake_call(*args, **kwargs):
            # The zoomed image is 2x the cropped section; coordinates are
            # relative to the zoomed image.
            return {
                "content": '{"bbox": [200, 200, 300, 280]}',
                "usage": None,
            }

        context = await mock_interface.get_context()

        async def fake_element_locate(*args, **kwargs):
            return {
                "parse_result": {
                    "element": {"center": (200, 200), "rect": {"left": 200, "top": 200, "width": 100, "height": 80}},
                    "errors": [],
                },
                "raw_response": "",
                "usage": None,
            }

        with patch(
            "midscene.core.service.index.call_generative_ai",
            new=fake_call,
        ), patch(
            "midscene.core.service.index.ai_locate_element",
            new=fake_element_locate,
        ):
            result = await locate_service(
                query_prompt="the button",
                context=context,
                model_runtime=_make_runtime(),
                deep_locate=True,
                plan_located_element={"center": (160, 120), "rect": None},
            )

        element = result["element"]
        assert element["center"][0] > 0
        assert result["deep_locate"] is True
        assert result["search_area"] is not None



class TestDeepLocatePlanHint:
    """deepLocate must not let plan coordinates shortcut the two-stage locate
    (upstream task-builder: elementFromPlan = deepLocate ? undefined : ...)."""

    @pytest.mark.asyncio
    async def test_plan_coords_become_search_hint(self, mock_interface):
        from midscene.core.agent.agent import Agent
        from midscene.core.agent.agent_options import AgentOptions

        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config={
                    "MIDSCENE_MODEL_NAME": "m",
                    "MIDSCENE_MODEL_API_KEY": "k",
                    "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                    "MIDSCENE_MODEL_FAMILY": "gpt-5",
                }
            ),
        )

        captured: Dict[str, Any] = {}

        async def fake_locate_service(**kwargs):
            captured.update(kwargs)
            return {
                "element": {"center": (123, 45), "rect": None, "description": "x"},
                "errors": [],
                "raw_response": "",
                "usage": None,
            }

        locate_param = {
            "prompt": "the button",
            "locatedPixelResult": {"center": (160, 120)},
            "deepLocate": True,
        }
        with patch(
            "midscene.core.agent.task_builder.locate_service", new=fake_locate_service
        ):
            element = await agent._locate_for_action(locate_param)

        # The plan coordinates were NOT returned directly; they were forwarded
        # as the search-area hint for the two-stage locate.
        assert element["center"] == (123, 45)
        assert captured["deep_locate"] is True
        assert captured["plan_located_element"] == {"center": (160, 120)}

    @pytest.mark.asyncio
    async def test_plan_coords_direct_hit_without_deep_locate(self, mock_interface):
        from midscene.core.agent.agent import Agent
        from midscene.core.agent.agent_options import AgentOptions

        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config={
                    "MIDSCENE_MODEL_NAME": "m",
                    "MIDSCENE_MODEL_API_KEY": "k",
                    "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                    "MIDSCENE_MODEL_FAMILY": "gpt-5",
                }
            ),
        )

        async def fail_if_called(**kwargs):
            raise AssertionError("locate_service should not run for a plan direct hit")

        locate_param = {
            "prompt": "the button",
            "locatedPixelResult": {"center": (160, 120)},
        }
        with patch("midscene.core.agent.task_builder.locate_service", new=fail_if_called):
            element = await agent._locate_for_action(locate_param)
        assert element["center"] == (160, 120)
