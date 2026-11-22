"""Synced from upstream packages/core/tests/unit-test/llm-planning.test.ts and
prompt/planning/action-output-example.test.ts."""

import base64
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.ai_model.model_adapter.default_planning_protocol import (
    build_planning_action_output,
    create_default_planning_protocol,
)
from midscene.core.device import DeviceAction, build_web_action_space
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
        self.tapped: List[tuple] = []
        self.typed: List[str] = []

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

    async def action_space(self):
        return ["tap", "input", "scroll"]

    async def tap(self, x, y):
        self.tapped.append((x, y))

    async def input_text(self, text):
        self.typed.append(text)

    async def keyboard_press(self, key):
        pass

    async def clear_input(self):
        pass

    async def replace_input(self, text):
        self.typed.append(text)

    async def scroll(self, direction, distance=None, **kwargs):
        pass


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


def test_serializes_an_action_type_and_structured_parameters():
    protocol = create_default_planning_protocol()
    output = build_planning_action_output(
        {
            "actionName": "Tap",
            "param": {"locate": {"prompt": "the button", "bbox": [1, 2, 3, 4]}},
            "locateFields": ["locate"],
            "locateResultKey": "bbox",
        }
    )

    assert "<action-type>Tap</action-type>" in output
    assert "[1, 2, 3, 4]" in output

    parsed = protocol["action_output_protocol"]["parse_action_output"](output, [])
    assert parsed["type"] == "Tap"
    assert parsed["param"]["locate"]["bbox"] == [1, 2, 3, 4]


def test_should_parse_xml_response_with_null_action():
    protocol = create_default_planning_protocol()

    assert (
        protocol["action_output_protocol"]["parse_action_output"](
            "<action-type>null</action-type>", []
        )
        is None
    )


def test_should_strip_trailing_xml_tags_leaked_into_action_type_by_llm():
    protocol = create_default_planning_protocol()

    parsed = protocol["action_output_protocol"]["parse_action_output"](
        "<action-type>Tap<extra></action-type>", []
    )

    assert parsed["type"] == "Tap"


def test_inline_single_string_shortcut_for_launch():
    from midscene.core.common import build_yaml_flow_from_plans

    tap = DeviceAction(
        name="Tap",
        description="",
        param_schema={"locate": {}},
        locate_fields=["locate"],
        interface_alias="aiTap",
    )
    launch = DeviceAction(
        name="Launch",
        description="",
        param_schema={"uri": {}},
        interface_alias="launch",
    )
    flow = build_yaml_flow_from_plans(
        [
            {"type": "Tap", "param": {"locate": {"prompt": "login"}}},
            {"type": "Launch", "param": {"uri": "app://x"}},
        ],
        [tap, launch],
    )

    assert flow[0] == {"aiTap": "", "locate": "login"}
    assert flow[1] == {"launch": "app://x"}


def _tap_response() -> str:
    return (
        "<planning>tap the button</planning>\n"
        "<log>Tap the button</log>\n"
        "<action-type>Tap</action-type>\n"
        "<action-param-json>\n"
        '{"locate": {"prompt": "the test button"}}\n'
        "</action-param-json>"
    )


def _complete_response(success: bool = True) -> str:
    message = "done" if success else "failed"
    return (
        f'<planning>finished</planning>\n<complete success="'
        f"{'true' if success else 'false'}\">{message}</complete>"
    )


@pytest.mark.asyncio
async def test_should_parse_complete_xml_response_with_all_fields(mock_interface):
    from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

    responses = [_tap_response(), _complete_response()]
    call_count = {"n": 0}

    async def handler(*args, **kwargs):
        call_count["n"] += 1
        return {
            "content": responses[call_count["n"] - 1],
            "usage": {"total_tokens": 1},
        }

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning", handler
    ):
        context = await mock_interface.get_context()
        result = await standard_plan(
            user_instruction="tap the test button",
            context=context,
            model_runtime=make_runtime(),
            action_space=build_web_action_space(),
            conversation_history=ConversationHistory(),
        )

    assert result["action"]["type"] == "Tap"
    assert result["action"]["param"]["locate"]["prompt"] == "the test button"
    assert result["thought"] == "tap the button"
    assert result["log"] == "Tap the button"
    assert "Tap" in result["yaml_flow"]


@pytest.mark.asyncio
async def test_should_parse_complete_tag_with_success_true_and_message(mock_interface):
    from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {"content": _complete_response(True), "usage": None},
    ):
        context = await mock_interface.get_context()
        result = await standard_plan(
            user_instruction="do nothing",
            context=context,
            model_runtime=make_runtime(),
            action_space=build_web_action_space(),
            conversation_history=ConversationHistory(),
        )

    assert result["finalize_success"] is True
    assert result["should_continue_planning"] is False
    assert result["actions"] == []


@pytest.mark.asyncio
async def test_throws_when_planned_action_is_not_in_action_space(mock_interface):
    from midscene.core.ai_model.service_caller.types import AIResponseParseError
    from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

    bad_response = (
        "<action-type>DoMagic</action-type>\n"
        "<action-param-json>\n{}\n</action-param-json>"
    )
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {"content": bad_response, "usage": None},
    ):
        context = await mock_interface.get_context()
        with pytest.raises(AIResponseParseError) as exc:
            await standard_plan(
                user_instruction="magic",
                context=context,
                model_runtime=make_runtime(),
                action_space=build_web_action_space(),
                conversation_history=ConversationHistory(),
            )

    assert "DoMagic not found" in str(exc.value)


@pytest.mark.asyncio
async def test_normalizes_locate_coordinates_in_planning(mock_interface):
    from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

    response = (
        "<planning>x</planning>\n"
        "<action-type>Tap</action-type>\n"
        "<action-param-json>\n"
        '{"locate": {"prompt": "button", "bbox_2d": [100, 100, 200, 200]}}\n'
        "</action-param-json>"
    )
    runtime = make_runtime(modelFamily="qwen3-vl", retryCount=0)
    with patch_model_call(
        "midscene.core.ai_model.workflows.planning.standard_planning",
        lambda *a, **k: {"content": response, "usage": None},
    ):
        context = await mock_interface.get_context()
        result = await standard_plan(
            user_instruction="tap",
            context=context,
            model_runtime=runtime,
            action_space=build_web_action_space(),
            conversation_history=ConversationHistory(),
            include_locate_in_planning=True,
        )

    located = result["action"]["param"]["locate"]["locatedPixelResult"]
    # bbox_2d is normalized to 0-1000: 100..200 maps to 32..64 px on a
    # 320-wide image and 24..48 px on a 240-high image. Closed intervals
    # center at 48.5/36.5, which Math.round-style rounding sends up.
    assert located["center"] == (49, 37)
