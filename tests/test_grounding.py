"""Synced from upstream packages/core/tests/unit-test/grounding-locate-not-found.test.ts
and jev.test.ts."""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.types import (
    BaseElement,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)


def make_png_base64(width: int = 320, height: int = 240) -> str:
    from PIL import Image
    import io

    image = Image.new("RGB", (width, height), (200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_empty_tree() -> UITree:
    return UITree(
        node=UINode(
            id="root",
            content="",
            rect=Rect(left=0, top=0, width=0, height=0),
            center=(0, 0),
            node_type=NodeType.CONTAINER,
        )
    )


class MockInterface:
    def __init__(self):
        self.interface_type = "web"
        self._context = None

    async def get_context(self) -> UIContext:
        if self._context:
            return self._context
        return UIContext(
            screenshot_base64=make_png_base64(),
            size=Size(width=320, height=240),
            content=[
                BaseElement(
                    id="test_element",
                    content="Test Button",
                    rect=Rect(left=100, top=100, width=200, height=50),
                    center=(200, 125),
                    node_type=NodeType.BUTTON,
                )
            ],
            tree=make_empty_tree(),
        )


@pytest.fixture
def mock_interface():
    return MockInterface()


def make_runtime(**config_overrides):
    from midscene.core.ai_model.models.registry import get_model_runtime

    config = {
        "modelName": "mock-model",
        "intent": "default",
        "slot": "default",
        "retryCount": 0,
        "retryInterval": 0,
        "responseFormat": "none",
    }
    config.update(config_overrides)
    return get_model_runtime(config)


def patch_model_call(module_path: str, handler):
    target = f"{module_path}.call_generative_ai"
    return patch(target, new=AsyncMock(side_effect=handler))


@pytest.mark.asyncio
async def test_locates_the_requested_element(mock_interface):
    from midscene.core.ai_model.workflows import ai_locate_element

    response_payload = '```json\n{"bbox": [100, 100, 199, 199]}\n```'

    with patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate",
        lambda *args, **kwargs: {
            "content": response_payload,
            "reasoning_content": None,
            "usage": {"total_tokens": 10},
        },
    ):
        context = await mock_interface.get_context()
        result = await ai_locate_element(
            target_element_description="the test button",
            context=context,
            model_runtime=make_runtime(),
        )

    element = result["parse_result"]["element"]
    # The default locate format is normalized to 0-1000 (upstream parity):
    # [100, 100, 199, 199] maps to 32..64 px on a 320-wide image and
    # 24..48 px on a 240-high image.
    assert element["center"] == (48, 36)
    assert element["rect"]["left"] == 32


@pytest.mark.asyncio
async def test_skips_coordinate_parsing_when_result_key_is_an_empty_array(
    mock_interface,
):
    from midscene.core.ai_model.workflows import ai_locate_element

    with patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate",
        lambda *args, **kwargs: {
            "content": '{"bbox": [], "error": "no such button"}',
            "usage": None,
        },
    ):
        context = await mock_interface.get_context()
        result = await ai_locate_element(
            target_element_description="missing button",
            context=context,
            model_runtime=make_runtime(),
        )

    assert result["parse_result"]["element"] is None
    assert result["parse_result"]["errors"] == ["no such button"]


@pytest.mark.asyncio
async def test_retries_json_parsing_through_the_same_locate_retry_loop(
    mock_interface,
):
    from midscene.core.ai_model.workflows import ai_locate_element

    calls = {"count": 0}

    async def handler(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"content": "not json at all", "usage": None}
        return {"content": '{"bbox": [0, 0, 9, 9]}', "usage": None}

    with patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate", handler
    ):
        context = await mock_interface.get_context()
        result = await ai_locate_element(
            target_element_description="retry target",
            context=context,
            model_runtime=make_runtime(retryCount=1, retryInterval=0),
        )

    assert calls["count"] == 2
    # Normalized 0-1000 closed bbox: [0, 0, 9, 9] spans [0, 2.88] px,
    # whose closed interval center rounds to (2, 2).
    assert result["parse_result"]["element"]["center"] == (2, 2)


@pytest.mark.asyncio
async def test_passes_locate_request_context_to_custom_locate_and_maps_its_bbox_result(
    mock_interface,
):
    from midscene.core.ai_model.workflows import ai_locate_element

    async def fake_system_one(runtime, request):
        return {
            "content": "raw",
            "usage": None,
            "answers": {
                "target": {
                    "type": "box",
                    "box": {"left": 0.0, "top": 0.0, "right": 0.5, "bottom": 0.5},
                }
            },
        }

    with patch(
        "midscene.core.ai_model.models.jev.locate.call_system_one",
        new=fake_system_one,
    ), patch_model_call(
        "midscene.core.ai_model.workflows.grounding.locate",
        AsyncMock(
            side_effect=AssertionError("standard locate path should not run")
        ),
    ):
        context = await mock_interface.get_context()
        result = await ai_locate_element(
            target_element_description="the test button",
            context=context,
            model_runtime=make_runtime(modelFamily="jev"),
        )

    element = result["parse_result"]["element"]
    assert element["center"] == (80, 60)
    assert element["description"] == "the test button"
