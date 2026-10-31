"""
Test suite for Midscene Python core functionality (upstream-synced architecture)
"""

import base64
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.types import (
    AgentOptions,
    NodeType,
    Rect,
    ScrollParam,
    BaseElement,
    Size,
    UIContext,
    UITree,
    UINode,
)


def make_png_base64(width: int = 320, height: int = 240) -> str:
    """A tiny valid PNG screenshot (solid color)."""
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
    """Mock interface for testing"""

    def __init__(self):
        self.interface_type = "web"
        self._context = None
        self.tapped: List[tuple] = []
        self.typed: List[str] = []
        self.keys: List[str] = []
        self.scrolled: List[tuple] = []

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
        self.keys.append(key)

    async def clear_input(self):
        pass

    async def replace_input(self, text):
        self.typed.append(text)

    async def scroll(self, direction, distance=None, **kwargs):
        self.scrolled.append((direction, distance, kwargs))


@pytest.fixture
def mock_interface():
    return MockInterface()


def make_runtime(**config_overrides):
    from midscene.core.ai_model.adapters import get_model_runtime

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
    """Patch call_generative_ai in a workflow module with an async handler."""
    target = f"{module_path}.call_generative_ai"
    return patch(target, new=AsyncMock(side_effect=handler))


# ---------------------------------------------------------------------------
# env_config
# ---------------------------------------------------------------------------


class TestEnvConfig:
    def _config_map(self, **overrides) -> Dict[str, str]:
        base = {
            "MIDSCENE_MODEL_NAME": "doubao-seed-1-6",
            "MIDSCENE_MODEL_API_KEY": "sk-test",
            "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        }
        base.update(overrides)
        return base

    def test_default_slot(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(self._config_map())
        config = manager.get_model_config("default")
        assert config["modelName"] == "doubao-seed-1-6"
        assert config["intent"] == "default"
        assert config["slot"] == "default"

    def test_slot_fallback_to_default(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(self._config_map())
        locate_config = manager.get_model_config("locate")
        assert locate_config["modelName"] == "doubao-seed-1-6"
        assert locate_config["slot"] == "default"

    def test_dedicated_locate_slot(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(
            self._config_map(
                MIDSCENE_LOCATE_MODEL_NAME="qwen3-vl-max",
                MIDSCENE_LOCATE_MODEL_FAMILY="qwen3-vl",
                MIDSCENE_LOCATE_MODEL_BASE_URL="https://example.com/v1",
                MIDSCENE_LOCATE_MODEL_API_KEY="sk-locate",
            )
        )
        locate_config = manager.get_model_config("locate")
        assert locate_config["modelName"] == "qwen3-vl-max"
        assert locate_config["modelFamily"] == "qwen3-vl"
        assert locate_config["slot"] == "locate"
        # planning still falls back
        assert manager.get_model_config("planning")["slot"] == "default"

    def test_legacy_vision_mode_mapping(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(
            self._config_map(MIDSCENE_USE_QWEN3_VL="1")
        )
        config = manager.get_model_config("default")
        assert config["modelFamily"] == "qwen3-vl"

    def test_missing_model_name_raises(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager({"MIDSCENE_MODEL_API_KEY": "sk"})
        with pytest.raises(Exception) as exc:
            manager.get_model_config("default")
        assert "MIDSCENE_MODEL_NAME" in str(exc.value)

    def test_invalid_family_raises(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(
            self._config_map(MIDSCENE_MODEL_FAMILY="not-a-family")
        )
        with pytest.raises(ValueError) as exc:
            manager.get_model_config("default")
        assert "Invalid MIDSCENE_MODEL_FAMILY" in str(exc.value)

    def test_vision_mode_conflict_raises(self):
        from midscene.core.ai_model.env_config import (
            legacy_config_to_model_family,
        )

        with pytest.raises(ValueError):
            legacy_config_to_model_family(
                {"MIDSCENE_USE_QWEN_VL": "1", "MIDSCENE_USE_GEMINI": "1"}
            )

    def test_retry_and_temperature_parsing(self):
        from midscene.core.ai_model.env_config import ModelConfigManager

        manager = ModelConfigManager(
            self._config_map(
                MIDSCENE_MODEL_TEMPERATURE="0.5",
                MIDSCENE_MODEL_RETRY_COUNT="2",
                MIDSCENE_MODEL_TIMEOUT="60",
            )
        )
        config = manager.get_model_config("default")
        assert config["temperature"] == 0.5
        assert config["retryCount"] == 2
        assert config["timeout"] == 60


# ---------------------------------------------------------------------------
# locate_result codec
# ---------------------------------------------------------------------------


class TestLocateResult:
    def test_pixel_bbox(self):
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(
            {
                "resultKey": "bbox",
                "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
            }
        )
        result = codec.to_pixel_result(
            [100, 100, 199, 199], {"preparedSize": {"width": 320, "height": 240}}
        )
        # Pixel inputs keep their precision; the bbox midpoint is 149.5
        assert result["center"] == (149.5, 149.5)
        rect = result["rect"]
        assert rect["left"] == 100 and rect["top"] == 100
        assert rect["width"] == 100 and rect["height"] == 100

    def test_normalized_bbox_1000(self):
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(
            {
                "resultKey": "bbox_2d",
                "coordinates": {
                    "shape": "bbox",
                    "order": "xy",
                    "normalizedBy": 1000,
                    "rounding": "round",
                },
            }
        )
        # 500/1000 of 320 = 160, 250/1000 of 240 = 60
        result = codec.to_pixel_result(
            [0, 0, 500, 250], {"preparedSize": {"width": 320, "height": 240}}
        )
        assert result["center"] == (80, 30)

    def test_yx_order_point(self):
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(
            {
                "resultKey": "point",
                "coordinates": {"shape": "point", "order": "yx", "rounding": "round"},
            }
        )
        result = codec.to_pixel_result(
            [30, 40], {"preparedSize": {"width": 320, "height": 240}}
        )
        assert result["center"] == (40, 30)
        assert result["rect"] is None

    def test_qwen25_flexible_parser(self):
        from midscene.core.ai_model.adapters import QWEN25_LOCATE_FORMAT
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(QWEN25_LOCATE_FORMAT)
        bbox_result = codec.to_pixel_result(
            [10, 10, 110, 60], {"preparedSize": {"width": 320, "height": 240}}
        )
        assert bbox_result["rect"] is not None
        point_result = codec.to_pixel_result(
            [10, 10], {"preparedSize": {"width": 320, "height": 240}}
        )
        assert point_result["center"] == (10, 10)
        assert point_result["rect"] is None

    def test_out_of_range_raises(self):
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(
            {
                "resultKey": "bbox",
                "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
            }
        )
        with pytest.raises(ValueError):
            codec.to_pixel_result(
                [0, 0, 5000, 5000], {"preparedSize": {"width": 320, "height": 240}}
            )

    def test_string_coordinates(self):
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        codec = create_locate_result_codec(
            {
                "resultKey": "bbox",
                "coordinates": {"shape": "bbox", "order": "xy", "rounding": "round"},
            }
        )
        result = codec.to_pixel_result(
            "100, 100, 199, 199", {"preparedSize": {"width": 320, "height": 240}}
        )
        assert result["center"] == (149.5, 149.5)


# ---------------------------------------------------------------------------
# xml / json utils
# ---------------------------------------------------------------------------


class TestXmlJsonUtils:
    def test_extract_xml_tag_basic(self):
        from midscene.core.ai_model.xml_utils import extract_xml_tag

        assert extract_xml_tag("<log>hello</log>", "log") == "hello"

    def test_extract_xml_tag_case_insensitive(self):
        from midscene.core.ai_model.xml_utils import extract_xml_tag

        assert extract_xml_tag("<LOG>hello</LOG>", "log") == "hello"

    def test_extract_xml_tag_last_occurrence(self):
        from midscene.core.ai_model.xml_utils import extract_xml_tag

        content = "<log>first</log>middle<log>second</log>"
        assert extract_xml_tag(content, "log") == "second"

    def test_extract_xml_tag_half_open(self):
        from midscene.core.ai_model.xml_utils import extract_xml_tag

        assert extract_xml_tag("<action-type>Input", "action-type") == "Input"

    def test_extract_xml_tag_with_thinking_prefix(self):
        from midscene.core.ai_model.xml_utils import extract_xml_tag

        content = "<think>let me think</think><planning>real plan</planning>"
        assert extract_xml_tag(content, "planning") == "real plan"

    def test_parse_json_from_code_fence(self):
        from midscene.core.ai_model.json_utils import parse_model_response_json

        raw = '```json\n{"bbox": [1, 2, 3, 4]}\n```'
        assert parse_model_response_json(raw) == {"bbox": [1, 2, 3, 4]}

    def test_parse_json_repairs_trailing_comma(self):
        from midscene.core.ai_model.json_utils import parse_model_response_json

        raw = '{"bbox": [1, 2, 3, 4], "prompt": "the button",}'
        assert parse_model_response_json(raw)["bbox"] == [1, 2, 3, 4]

    def test_parse_json_trims_values(self):
        from midscene.core.ai_model.json_utils import parse_model_response_json

        parsed = parse_model_response_json('{"type": " Tap "}')
        assert parsed["type"] == "Tap"

    def test_parse_json_preserve_string_value_keys(self):
        from midscene.core.ai_model.json_utils import parse_model_response_json

        parsed = parse_model_response_json(
            '{"value": " spaced ", "type": " Tap "}',
            preserve_string_value_keys=["value"],
        )
        assert parsed["value"] == " spaced "
        assert parsed["type"] == "Tap"

    def test_assert_json_object_rejects_array(self):
        from midscene.core.ai_model.json_utils import assert_json_object

        with pytest.raises(ValueError):
            assert_json_object([1, 2])


# ---------------------------------------------------------------------------
# protocols
# ---------------------------------------------------------------------------


class TestProtocols:
    def test_planning_build_and_parse_action_output(self):
        from midscene.core.ai_model.protocols import (
            build_planning_action_output,
            create_default_planning_protocol,
        )

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

        parsed = protocol["action_output_protocol"]["parse_action_output"](
            output, []
        )
        assert parsed["type"] == "Tap"
        assert parsed["param"]["locate"]["bbox"] == [1, 2, 3, 4]

    def test_planning_parse_null_action(self):
        from midscene.core.ai_model.protocols import create_default_planning_protocol

        protocol = create_default_planning_protocol()
        assert (
            protocol["action_output_protocol"]["parse_action_output"]("<action-type>null</action-type>", [])
            is None
        )

    def test_planning_parse_leaked_xml_in_type(self):
        from midscene.core.ai_model.protocols import create_default_planning_protocol

        protocol = create_default_planning_protocol()
        parsed = protocol["action_output_protocol"]["parse_action_output"](
            "<action-type>Tap<extra></action-type>", []
        )
        assert parsed["type"] == "Tap"

    def test_locate_protocol_parse_response(self):
        from midscene.core.ai_model.protocols import create_default_element_protocol

        protocol = create_default_element_protocol()
        prompt_spec = {
            "resultKey": "bbox",
            "resultKeyAliases": [],
            "exampleValues": [[1, 2, 3, 4]],
        }
        parsed = protocol["parse_raw_response"](
            '```json\n{"bbox": [10, 10, 20, 20]}\n```', prompt_spec
        )
        assert parsed["kind"] == "located"
        assert parsed["target"] == [10, 10, 20, 20]

        not_found = protocol["parse_raw_response"](
            '{"bbox": [], "error": "not found"}', prompt_spec
        )
        assert not_found["kind"] == "not-found"
        assert not_found["error"] == "not found"

    def test_locate_protocol_missing_field(self):
        from midscene.core.ai_model.protocols import create_default_element_protocol

        protocol = create_default_element_protocol()
        prompt_spec = {"resultKey": "bbox", "resultKeyAliases": []}
        with pytest.raises(ValueError) as exc:
            protocol["parse_raw_response"]('{"wrong": [1,2,3,4]}', prompt_spec)
        assert "Missing required coordinate field" in str(exc.value)

    def test_insight_protocol_parse(self):
        from midscene.core.ai_model.protocols import create_default_insight_protocol

        protocol = create_default_insight_protocol()
        data_output = protocol["data_output"]
        parsed = data_output["parse"]("<data-json>{\"title\": \"Test Page\"}</data-json>")
        assert parsed == {"title": "Test Page"}
        assert data_output["build_example"]('"x"') == '<data-json>\n"x"\n</data-json>'


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_planning_system_prompt_contains_key_sections(self):
        from midscene.core.actions import build_web_action_space
        from midscene.core.ai_model.adapters import get_model_adapter
        from midscene.core.ai_model.prompts.planning import (
            build_standard_planning_system_prompt,
        )

        adapter = get_model_adapter("qwen3-vl")
        prompt = build_standard_planning_system_prompt(
            action_space=build_web_action_space(),
            planning_protocol=adapter.planning_protocol,
            include_locate_in_planning=True,
            locate_prompt_spec=adapter.locate_result_codec.prompt_spec,
        )
        assert "<planning>" in prompt
        assert "Supporting actions list" in prompt
        assert "type: Tap" in prompt or "- type: Tap" in prompt
        assert "<action-type>" in prompt
        assert "Multi-turn Conversation Example" in prompt
        assert "bbox_2d" in prompt

    def test_insight_system_prompt(self):
        from midscene.core.ai_model.prompts.insight import build_insight_system_prompt
        from midscene.core.ai_model.protocols import create_default_insight_protocol

        prompt = build_insight_system_prompt(create_default_insight_protocol())
        assert "DATA_DEMAND" in prompt
        assert "data-json" in prompt
        assert "<observation>" in prompt

    def test_extract_data_query_prompt(self):
        from midscene.core.ai_model.prompts.insight import extract_data_query_prompt

        prompt = extract_data_query_prompt("a login page", {"title": "string"})
        assert "<PageDescription>" in prompt
        assert "a login page" in prompt
        assert "<DATA_DEMAND>" in prompt

    def test_locate_system_prompt_grounding_rules(self):
        from midscene.core.ai_model.prompts.locate import (
            build_element_locate_system_prompt,
        )

        prompt = build_element_locate_system_prompt("Intro", "Output")
        assert "Important Notes for Locating Elements" in prompt
        assert "Intro" in prompt and "Output" in prompt

    def test_describe_prompt(self):
        from midscene.core.ai_model.prompts.describe import (
            element_describer_instruction,
        )

        instruction = element_describer_instruction()
        assert "ring with a crosshair" in instruction
        assert '"description"' in instruction


# ---------------------------------------------------------------------------
# caller
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"x-request-id": "req-1"}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestCaller:
    def _chat_payload(
        self,
        content: str,
        reasoning: Optional[str] = None,
        model: str = "mock-model",
    ) -> Dict[str, Any]:
        message: Dict[str, Any] = {"role": "assistant", "content": content}
        if reasoning:
            message["reasoning_content"] = reasoning
        return {
            "id": "chatcmpl-1",
            "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    async def _run_call(self, responses, model_config_overrides=None, **call_options):
        from midscene.core.ai_model import caller

        it = iter(responses)

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, json=None):
                response = next(it)
                if isinstance(response, Exception):
                    raise response
                return response

        with patch.object(caller.httpx, "AsyncClient", FakeAsyncClient):
            runtime = make_runtime(**(model_config_overrides or {}))
            return await caller.call_generative_ai(
                [{"role": "user", "content": "hi"}], runtime, call_options
            )

    @pytest.mark.asyncio
    async def test_basic_call(self):
        result = await self._run_call(
            [FakeResponse(self._chat_payload("hello world"))]
        )
        assert result["content"] == "hello world"
        assert result["usage"]["total_tokens"] == 150
        assert result["usage"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_reasoning_fallback(self):
        result = await self._run_call(
            [FakeResponse(self._chat_payload("", reasoning="thinking output"))]
        )
        assert result["content"] == "thinking output"

    @pytest.mark.asyncio
    async def test_empty_content_raises_parse_error(self):
        from midscene.core.ai_model.caller import AIResponseParseError

        with pytest.raises(AIResponseParseError):
            await self._run_call(
                [FakeResponse(self._chat_payload("", reasoning=None))]
            )

    @pytest.mark.asyncio
    async def test_retry_on_http_error(self):
        result = await self._run_call(
            [
                FakeResponse({"error": "boom"}, status_code=500),
                FakeResponse(self._chat_payload("recovered")),
            ],
            model_config_overrides={"retryCount": 1, "retryInterval": 0},
        )
        assert result["content"] == "recovered"

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        with pytest.raises(RuntimeError) as exc:
            await self._run_call(
                [
                    FakeResponse({"error": "boom"}, status_code=500),
                    FakeResponse({"error": "boom"}, status_code=500),
                ],
                model_config_overrides={"retryCount": 1, "retryInterval": 0},
            )
        assert "1 retry" in str(exc.value) or "retries" in str(exc.value)

    @pytest.mark.asyncio
    async def test_model_family_params_applied(self):
        runtime = make_runtime(modelFamily="qwen3-vl")
        params = runtime.adapter.build_chat_completion_params(
            {"temperature": 0.0}, {"reasoningEnabled": True}
        )
        assert params["enable_thinking"] is True

        runtime_qwen25 = make_runtime(modelFamily="qwen2.5-vl")
        params25 = runtime_qwen25.adapter.build_chat_completion_params({}, {})
        assert params25["vl_high_resolution_images"] is True


# ---------------------------------------------------------------------------
# workflows (grounding / insight / planning)
# ---------------------------------------------------------------------------


class TestGroundingWorkflow:
    @pytest.mark.asyncio
    async def test_locate_success(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_locate_element

        response_payload = '```json\n{"bbox": [100, 100, 199, 199]}\n```'

        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding",
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
    async def test_locate_not_found(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_locate_element

        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding",
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
    async def test_locate_retries_on_parse_error(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_locate_element

        calls = {"count": 0}

        async def handler(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"content": "not json at all", "usage": None}
            return {"content": '{"bbox": [0, 0, 9, 9]}', "usage": None}

        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding", handler
        ):
            context = await mock_interface.get_context()
            result = await ai_locate_element(
                target_element_description="retry target",
                context=context,
                model_runtime=make_runtime(retryCount=1, retryInterval=0),
            )

        assert calls["count"] == 2
        # Normalized 0-1000 input: midpoint 4.5 -> ~1.44 x 1.08 px -> (1, 1)
        assert result["parse_result"]["element"]["center"] == (1, 1)


class TestInsightWorkflow:
    @pytest.mark.asyncio
    async def test_extract(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_extract_element_info

        raw = (
            "<observation>page title visible</observation>\n"
            "<data-json>{\"title\": \"Test Page\"}</data-json>"
        )
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight",
            lambda *args, **kwargs: {"content": raw, "usage": {"total_tokens": 5}},
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
    async def test_boolean(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_extract_element_info

        raw = '<observation>yes</observation>\n<data-json>{"assertion": true}</data-json>'
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight",
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
    async def test_boolean_requires_single_field(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_extract_element_info

        context = await mock_interface.get_context()
        with pytest.raises(ValueError):
            await ai_extract_element_info(
                task_type="boolean",
                data_query={"a": "x", "b": "y"},
                context=context,
                model_runtime=make_runtime(),
            )


class TestPlanningWorkflow:
    def _tap_response(self) -> str:
        return (
            "<planning>tap the button</planning>\n"
            "<log>Tap the button</log>\n"
            "<action-type>Tap</action-type>\n"
            "<action-param-json>\n"
            '{"locate": {"prompt": "the test button"}}\n'
            "</action-param-json>"
        )

    def _complete_response(self, success: bool = True) -> str:
        message = "done" if success else "failed"
        return f"<planning>finished</planning>\n<complete success=\"{'true' if success else 'false'}\">{message}</complete>"

    @pytest.mark.asyncio
    async def test_standard_plan_action(self, mock_interface):
        from midscene.core.actions import build_web_action_space
        from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

        responses = [self._tap_response(), self._complete_response()]
        call_count = {"n": 0}

        async def handler(*args, **kwargs):
            call_count["n"] += 1
            return {"content": responses[call_count["n"] - 1], "usage": {"total_tokens": 1}}

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", handler
        ):
            context = await mock_interface.get_context()
            history = ConversationHistory()
            result = await standard_plan(
                user_instruction="tap the test button",
                context=context,
                model_runtime=make_runtime(),
                action_space=build_web_action_space(),
                conversation_history=history,
            )

        assert result["action"]["type"] == "Tap"
        assert result["action"]["param"]["locate"]["prompt"] == "the test button"
        assert result["thought"] == "tap the button"
        assert result["log"] == "Tap the button"
        assert "Tap" in result["yaml_flow"]

    @pytest.mark.asyncio
    async def test_standard_plan_complete(self, mock_interface):
        from midscene.core.actions import build_web_action_space
        from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning",
            lambda *a, **k: {"content": self._complete_response(True), "usage": None},
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
    async def test_unknown_action_raises(self, mock_interface):
        from midscene.core.actions import build_web_action_space
        from midscene.core.ai_model.caller import AIResponseParseError
        from midscene.core.ai_model.workflows import ConversationHistory, standard_plan

        bad_response = (
            "<action-type>DoMagic</action-type>\n"
            "<action-param-json>\n{}\n</action-param-json>"
        )
        with patch_model_call(
            "midscene.core.ai_model.workflows.planning",
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
    async def test_planning_locate_coordinates_normalized(self, mock_interface):
        from midscene.core.actions import build_web_action_space
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
            "midscene.core.ai_model.workflows.planning",
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
        # 320-wide image and 24..48 px on a 240-high image.
        assert located["center"] == (48, 36)


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------


class TestAgent:
    @pytest.mark.asyncio
    async def test_agent_creation(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface)
        assert agent.interface == mock_interface
        assert agent.destroyed is False
        assert [a.name for a in agent.action_space][0] == "Tap"

    @pytest.mark.asyncio
    async def test_basic_actions(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface)
        await agent.tap(100, 200)
        await agent.input_text("test text")
        await agent.scroll(ScrollParam(direction="down", scroll_type="once", distance=500))
        assert mock_interface.tapped == [(100, 200)]
        assert mock_interface.typed == ["test text"]
        assert mock_interface.scrolled[0][0] == "down"

    @pytest.mark.asyncio
    async def test_agent_destroy(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface)
        await agent.destroy()
        assert agent.destroyed is True
        with pytest.raises(RuntimeError):
            await agent.ai_locate("test")

    @pytest.mark.asyncio
    async def test_ai_action_full_loop(self, mock_interface):
        """Plan -> execute Tap -> complete; interface receives the tap."""
        from midscene.core.agent import Agent

        responses = [
            (
                "<planning>tap</planning>\n"
                "<log>Tap the button</log>\n"
                "<action-type>Tap</action-type>\n"
                "<action-param-json>\n"
                '{"locate": {"prompt": "the test button", '
                '"bbox": [190, 115, 210, 135]}}\n'
                "</action-param-json>"
            ),
            '<complete success="true">finished</complete>',
        ]
        planning_calls = {"n": 0}
        locate_calls = {"n": 0}

        async def planning_handler(*args, **kwargs):
            planning_calls["n"] += 1
            return {"content": responses[planning_calls["n"] - 1], "usage": {"total_tokens": 7}}

        async def locate_handler(*args, **kwargs):
            locate_calls["n"] += 1
            return {
                "content": '{"bbox": [190, 115, 210, 135]}',
                "usage": {"total_tokens": 3},
            }

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ), patch_model_call(
            "midscene.core.ai_model.workflows.grounding", locate_handler
        ):
            agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))
            result = await agent.ai_action("tap the test button")

        assert result == "finished"  # finalize message from <complete>
        assert mock_interface.tapped == [(200, 125)]
        assert planning_calls["n"] == 2
        # Planning included pixel coordinates, so locate is not called again.
        assert locate_calls["n"] == 0

    @pytest.mark.asyncio
    async def test_ai_action_complete_false_raises(self, mock_interface):
        from midscene.core.agent import Agent

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning",
            lambda *a, **k: {
                "content": '<complete success="false">could not find it</complete>',
                "usage": None,
            },
        ):
            agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))
            with pytest.raises(AssertionError) as exc:
                await agent.ai_action("do the impossible")
        assert "could not find it" in str(exc.value)

    @pytest.mark.asyncio
    async def test_ai_action_retries_after_execution_error(self, mock_interface):
        """A failed locate does not abort the task; agent reports error feedback
        to the planner and continues."""
        from midscene.core.agent import Agent

        responses = [
            # first plan: tap a missing element
            (
                "<action-type>Tap</action-type>\n"
                "<action-param-json>\n"
                '{"locate": {"prompt": "missing element"}}\n'
                "</action-param-json>"
            ),
            # second plan: complete
            '<complete success="true">done</complete>',
        ]
        planning_calls = {"n": 0}

        async def planning_handler(*args, **kwargs):
            planning_calls["n"] += 1
            return {"content": responses[planning_calls["n"] - 1], "usage": None}

        async def locate_handler(*args, **kwargs):
            return {
                "content": '{"bbox": [], "error": "element not found"}',
                "usage": None,
            }

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ), patch_model_call(
            "midscene.core.ai_model.workflows.grounding", locate_handler
        ):
            agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))
            result = await agent.ai_action("retry flow")

        assert result == "done"
        assert planning_calls["n"] == 2
        assert mock_interface.tapped == []

    @pytest.mark.asyncio
    async def test_ai_locate(self, mock_interface):
        from midscene.core.agent import Agent

        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding",
            lambda *a, **k: {
                "content": '{"bbox": [190, 115, 210, 135]}',
                "usage": None,
                "raw_response": "raw",
            },
        ):
            agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))
            result = await agent.ai_locate("the test button")

        assert list(result.center) == [200, 125]
        assert result.rect.left == 190

    @pytest.mark.asyncio
    async def test_ai_input_legacy_signature(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface)
        calls = []

        async def fake_call(action_type, param=None):
            calls.append((action_type, param))

        agent._call_action_in_action_space = fake_call
        await agent.ai_input("hello", "the search box")

        assert calls == [
            ("Input", {"value": "hello", "locate": {"prompt": "the search box"}})
        ]

    @pytest.mark.asyncio
    async def test_ai_extract(self, mock_interface):
        from midscene.core.agent import Agent

        raw = '<data-json>{"username": "testuser"}</data-json>'
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight",
            lambda *a, **k: {"content": raw, "usage": None},
        ):
            agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))
            result = await agent.ai_extract("extract username")

        assert result == {"username": "testuser"}

    @pytest.mark.asyncio
    async def test_ai_assert_success_and_failure(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface, AgentOptions(model_config={
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }))

        with patch_model_call(
            "midscene.core.ai_model.workflows.insight",
            lambda *a, **k: {
                "content": '<data-json>{"StatementIsTruthy": true}</data-json>',
                "usage": None,
            },
        ):
            await agent.ai_assert("page is loaded")

        with patch_model_call(
            "midscene.core.ai_model.workflows.insight",
            lambda *a, **k: {
                "content": '<data-json>{"StatementIsTruthy": false}</data-json>',
                "usage": None,
            },
        ):
            with pytest.raises(AssertionError):
                await agent.ai_assert("user is logged in")

    @pytest.mark.asyncio
    async def test_model_config_dict(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(
            mock_interface,
            AgentOptions(
                model_config={
                    "MIDSCENE_MODEL_NAME": "m1",
                    "MIDSCENE_MODEL_API_KEY": "k",
                    "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                }
            ),
        )
        config = agent.model_runtime("default").config
        assert config["modelName"] == "m1"

    @pytest.mark.asyncio
    async def test_plan_cache_replay(self, mock_interface, tmp_path, monkeypatch):
        """Second ai_action with the same prompt replays the cached plan."""
        from midscene.core.agent import Agent
        from midscene.core.ai_model.env_config import MIDSCENE_RUN_DIR

        monkeypatch.setenv(MIDSCENE_RUN_DIR, str(tmp_path))

        planning_calls = {"n": 0}
        responses = [
            (
                "<action-type>Sleep</action-type>\n"
                "<action-param-json>\n"
                '{"timeMs": 1}\n'
                "</action-param-json>"
            ),
            '<complete success="true">done</complete>',
        ]

        async def planning_handler(*args, **kwargs):
            planning_calls["n"] += 1
            return {"content": responses[min(planning_calls["n"], 2) - 1], "usage": None}

        model_config = {
            "MIDSCENE_MODEL_NAME": "mock-model",
            "MIDSCENE_MODEL_API_KEY": "sk-test",
            "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
            "MIDSCENE_MODEL_FAMILY": "gpt-5",
        }
        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ):
            agent = Agent(
                mock_interface,
                AgentOptions(cache_id="cache-test", model_config=model_config),
            )
            await agent.ai_action("run the cached flow")
        assert planning_calls["n"] == 2

        with patch_model_call(
            "midscene.core.ai_model.workflows.planning", planning_handler
        ):
            agent2 = Agent(
                mock_interface,
                AgentOptions(cache_id="cache-test", model_config=model_config),
            )
            result = await agent2.ai_action("run the cached flow")

        assert planning_calls["n"] == 2  # no new planning calls
        assert result is None  # replay produces no finalize message

        # cleanup cache file
        agent2._task_cache.flush()


# ---------------------------------------------------------------------------
# task cache
# ---------------------------------------------------------------------------


class TestTaskCache:
    def test_plan_cache_roundtrip(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(cache_id="unit-test", enabled=True)
        cache.append_plan_cache("do something", "- type: Tap")

        cache2 = TaskCache(cache_id="unit-test", enabled=True)
        entry = cache2.match_plan_cache("do something")
        assert entry is not None
        assert entry["yamlWorkflow"] == "- type: Tap"

        # consumed entries do not match again
        assert cache2.match_plan_cache("do something") is None

    def test_missing_cache_returns_none(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(cache_id="empty", enabled=True)
        assert cache.match_plan_cache("nothing") is None

    def test_release_plan_cache_after_failed_replay(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(cache_id="release-test", enabled=True)
        cache.append_plan_cache("do something", "- type: Tap")

        assert cache.match_plan_cache("do something") is not None
        assert cache.match_plan_cache("do something") is None

        cache.release_plan_cache("do something")
        assert cache.match_plan_cache("do something") is not None

    @pytest.mark.asyncio
    async def test_cached_plan_replay_drops_stale_pixels(self, mock_interface):
        from midscene.core.agent import Agent

        agent = Agent(mock_interface)
        captured = []

        async def fake_execute(action):
            captured.append(action)

        agent._execute_planning_action = fake_execute
        yaml_workflow = (
            "tasks:\n"
            "  - name: t\n"
            "    flow:\n"
            "      - type: Tap\n"
            "        locate:\n"
            "          prompt: the button\n"
            "          locatedPixelResult:\n"
            "            center: [1, 2]\n"
        )

        assert await agent._replay_cached_plan({"yamlWorkflow": yaml_workflow})
        assert captured[0]["param"]["locate"] == {"prompt": "the button"}


# ---------------------------------------------------------------------------
# element-level locate cache
# ---------------------------------------------------------------------------


class _CacheInterface(MockInterface):
    """Mock interface exposing the optional locate-cache hooks."""

    def __init__(self):
        super().__init__()
        self.features: List[list] = []
        self.resolved: List[Dict[str, Any]] = []
        self.rect_to_return: Optional[Rect] = Rect(
            left=10, top=20, width=30, height=40
        )

    async def cache_feature_for_point(self, center, options=None):
        self.features.append(list(center))
        return {"xpaths": ["/html/body/button[1]"]}

    async def rect_matches_cache_feature(self, feature):
        self.resolved.append(feature)
        return self.rect_to_return


class TestLocateCache:
    def test_locate_cache_roundtrip(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(cache_id="locate-unit", enabled=True)
        cache.append_locate_cache("the button", {"xpaths": ["/html/body/button[1]"]})

        cache2 = TaskCache(cache_id="locate-unit", enabled=True)
        matched = cache2.match_locate_cache("the button")
        assert matched is not None
        assert matched["cache"] == {"xpaths": ["/html/body/button[1]"]}
        assert matched["index"] == 0
        # each entry is consumed once per run
        assert cache2.match_locate_cache("the button") is None

    def test_locate_cache_replaces_stale_entry(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(cache_id="locate-replace", enabled=True)
        cache.append_locate_cache("the button", {"xpaths": ["/old"]})
        matched = cache.match_locate_cache("the button")
        cache.append_locate_cache(
            "the button", {"xpaths": ["/new"]}, replace_index=matched["index"]
        )

        cache2 = TaskCache(cache_id="locate-replace", enabled=True)
        assert len(cache2.cache["caches"]) == 1
        assert cache2.match_locate_cache("the button")["cache"] == {"xpaths": ["/new"]}

    def test_locate_cache_read_only_does_not_write(self, tmp_path, monkeypatch):
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        cache = TaskCache(
            cache_id="locate-readonly", enabled=True, read_only_mode=True
        )
        cache.append_locate_cache("the button", {"xpaths": ["/x"]})

        cache2 = TaskCache(cache_id="locate-readonly", enabled=True)
        assert cache2.match_locate_cache("the button") is None

    @pytest.mark.asyncio
    async def test_agent_uses_cached_feature_without_ai(
        self, tmp_path, monkeypatch
    ):
        from midscene.core.agent import Agent

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        agent = Agent(interface, AgentOptions(cache_id="locate-hit"))
        agent._get_task_cache().append_locate_cache(
            "the button", {"xpaths": ["/cached"]}
        )

        async def fail_locate(*args, **kwargs):
            raise AssertionError("AI locate must not run on a cache hit")

        monkeypatch.setattr(agent, "_run_locate", fail_locate)
        result = await agent._locate_for_action({"prompt": "the button"})

        assert result["center"] == [25.0, 40.0]
        assert result["rect"] == Rect(left=10, top=20, width=30, height=40)
        assert interface.resolved == [{"xpaths": ["/cached"]}]

    @pytest.mark.asyncio
    async def test_agent_writes_cache_after_ai_locate(self, tmp_path, monkeypatch):
        from midscene.core.agent import Agent
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        agent = Agent(interface, AgentOptions(cache_id="locate-write"))

        async def fake_locate(*args, **kwargs):
            return {
                "center": [25, 40],
                "rect": Rect(left=10, top=20, width=30, height=40),
            }

        monkeypatch.setattr(agent, "_run_locate", fake_locate)
        await agent._locate_for_action({"prompt": "the button"})

        assert interface.features == [[25.0, 40.0]]
        reloaded = TaskCache(cache_id="locate-write", enabled=True)
        assert reloaded.match_locate_cache("the button")["cache"] == {
            "xpaths": ["/html/body/button[1]"]
        }

    @pytest.mark.asyncio
    async def test_agent_skips_cache_when_cacheable_false(
        self, tmp_path, monkeypatch
    ):
        from midscene.core.agent import Agent

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        agent = Agent(interface, AgentOptions(cache_id="locate-nocache"))

        async def fake_locate(*args, **kwargs):
            return {"center": [1, 2], "rect": None}

        monkeypatch.setattr(agent, "_run_locate", fake_locate)
        await agent._locate_for_action({"prompt": "the button", "cacheable": False})

        assert interface.features == []
        assert agent._get_task_cache().cache["caches"] == []

    @pytest.mark.asyncio
    async def test_agent_replaces_stale_cache_entry(self, tmp_path, monkeypatch):
        from midscene.core.agent import Agent
        from midscene.core.task_cache import TaskCache

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        interface.rect_to_return = None
        agent = Agent(interface, AgentOptions(cache_id="locate-stale"))
        agent._get_task_cache().append_locate_cache(
            "the button", {"xpaths": ["/stale"]}
        )

        async def fake_locate(*args, **kwargs):
            return {"center": [5, 6], "rect": None}

        monkeypatch.setattr(agent, "_run_locate", fake_locate)
        result = await agent._locate_for_action({"prompt": "the button"})

        assert result["center"] == [5, 6]
        assert interface.features == [[5.0, 6.0]]
        reloaded = TaskCache(cache_id="locate-stale", enabled=True)
        assert reloaded.match_locate_cache("the button")["cache"] == {
            "xpaths": ["/html/body/button[1]"]
        }

    @pytest.mark.asyncio
    async def test_agent_caches_plan_coordinates(self, tmp_path, monkeypatch):
        from midscene.core.agent import Agent

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        agent = Agent(interface, AgentOptions(cache_id="locate-plan"))
        result = await agent._locate_for_action(
            {
                "prompt": "the button",
                "locatedPixelResult": {"center": [7, 8]},
            }
        )

        assert result == {"center": [7, 8]}
        assert interface.features == [[7.0, 8.0]]

    @pytest.mark.asyncio
    async def test_plan_coordinates_win_over_cache(self, tmp_path, monkeypatch):
        from midscene.core.agent import Agent

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        interface = _CacheInterface()
        agent = Agent(interface, AgentOptions(cache_id="locate-plan-priority"))
        agent._get_task_cache().append_locate_cache(
            "the button", {"xpaths": ["/cached"]}
        )

        async def fail_locate(*args, **kwargs):
            raise AssertionError("AI locate must not run on a plan hit")

        monkeypatch.setattr(agent, "_run_locate", fail_locate)
        result = await agent._locate_for_action(
            {
                "prompt": "the button",
                "locatedPixelResult": {"center": [7, 8]},
            }
        )

        assert result == {"center": [7, 8]}
        assert interface.resolved == []
        assert interface.features == []
        assert len(agent._get_task_cache().cache["caches"]) == 1

    @pytest.mark.asyncio
    async def test_agent_does_not_cache_empty_feature(self, tmp_path, monkeypatch):
        from midscene.core.agent import Agent

        class EmptyFeatureInterface(_CacheInterface):
            async def cache_feature_for_point(self, center, options=None):
                self.features.append(list(center))
                return {"xpaths": []}

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        agent = Agent(EmptyFeatureInterface(), AgentOptions(cache_id="locate-empty"))

        async def fake_locate(*args, **kwargs):
            return {"center": [1, 2], "rect": None}

        monkeypatch.setattr(agent, "_run_locate", fake_locate)
        await agent._locate_for_action({"prompt": "the button"})

        assert agent._get_task_cache().cache["caches"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
