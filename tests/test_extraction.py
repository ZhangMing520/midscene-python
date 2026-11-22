"""Synced from upstream packages/core/tests/unit-test/extraction.test.ts and
insight-extract-prompt.test.ts."""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.ai_model.model_adapter.default_insight_protocol import (
    create_default_insight_protocol,
)
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


def test_default_insight_response_parser_builds_and_parses_data_json():
    protocol = create_default_insight_protocol()
    data_output = protocol["data_output"]

    parsed = data_output["parse"](
        '<data-json>{"title": "Test Page"}</data-json>'
    )

    assert parsed == {"title": "Test Page"}
    assert data_output["build_example"]('"x"') == '<data-json>\n"x"\n</data-json>'


@pytest.mark.asyncio
async def test_should_parse_complete_xml_response_with_all_fields(mock_interface):
    from midscene.core.ai_model.workflows import ai_extract_element_info

    raw = (
        "<observation>page title visible</observation>\n"
        '<data-json>{"title": "Test Page"}</data-json>'
    )
    with patch_model_call(
        "midscene.core.ai_model.workflows.insight.extraction",
        lambda *args, **kwargs: {
            "content": raw,
            "usage": {"total_tokens": 5},
        },
    ):
        context = await mock_interface.get_context()
        result = await ai_extract_element_info(
            task_type="extract",
            data_query="the page title",
            context=context,
            model_runtime=make_runtime(),
        )

    assert result["parse_result"]["data"] == {"title": "Test Page"}
    assert result["parse_result"]["thought"] == "page title visible"


@pytest.mark.asyncio
async def test_should_parse_xml_response_with_boolean_data(mock_interface):
    from midscene.core.ai_model.workflows import ai_extract_element_info

    raw = (
        "<observation>yes</observation>\n"
        '<data-json>{"assertion": true}</data-json>'
    )
    with patch_model_call(
        "midscene.core.ai_model.workflows.insight.extraction",
        lambda *args, **kwargs: {"content": raw, "usage": None},
    ):
        context = await mock_interface.get_context()
        result = await ai_extract_element_info(
            task_type="boolean",
            data_query={"assertion": "the page is loaded"},
            context=context,
            model_runtime=make_runtime(),
        )

    assert result["parse_result"]["data"] == {"assertion": True}


@pytest.mark.asyncio
async def test_boolean_demand_requires_a_single_field(mock_interface):
    from midscene.core.ai_model.workflows import ai_extract_element_info

    context = await mock_interface.get_context()
    with pytest.raises(ValueError):
        await ai_extract_element_info(
            task_type="boolean",
            data_query={"a": "x", "b": "y"},
            context=context,
            model_runtime=make_runtime(),
        )
