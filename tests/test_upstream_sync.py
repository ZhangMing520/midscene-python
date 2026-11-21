"""
Tests for the second wave of upstream alignment (v1.17.4):
System One / Jev, custom planners (UI-TARS / Auto-GLM), DeepLocate,
YAML runner, dump structure, connectivity, model fallback.
"""

import asyncio
import base64
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_core import (
    FakeResponse,
    MockInterface,
    make_png_base64,
    patch_model_call,
)

import pytest_asyncio  # noqa: F401


@pytest.fixture
def mock_interface():
    return MockInterface()


# ---------------------------------------------------------------------------
# System One protocol
# ---------------------------------------------------------------------------


class TestSystemOne:
    def _response(self, answers: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "model": "jev-1",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    def test_validate_response_accepts_valid(self):
        from midscene.core.ai_model.system_one import validate_system_one_response

        payload = self._response(
            {
                "present": {"type": "noul", "noul": 0.9},
                "target": {
                    "type": "box",
                    "box": {"left": 0.1, "top": 0.1, "right": 0.5, "bottom": 0.6},
                },
            }
        )
        validated = validate_system_one_response(payload)
        assert validated["answers"]["present"]["noul"] == 0.9

    def test_validate_response_rejects_bad_box(self):
        from midscene.core.ai_model.system_one import SystemOneError, validate_system_one_response

        payload = self._response(
            {
                "target": {
                    "type": "box",
                    "box": {"left": 0.6, "top": 0.1, "right": 0.5, "bottom": 0.6},
                }
            }
        )
        with pytest.raises(SystemOneError):
            validate_system_one_response(payload)

    def test_validate_response_rejects_probability_out_of_range(self):
        from midscene.core.ai_model.system_one import SystemOneError, validate_system_one_response

        payload = self._response({"present": {"type": "noul", "noul": 1.5}})
        with pytest.raises(SystemOneError):
            validate_system_one_response(payload)

    def test_encode_images_openrouter_inline(self):
        from midscene.core.ai_model.system_one import encode_system_one_images

        data_url = "data:image/png;base64,AAAA"
        state, assets = encode_system_one_images({"shot": data_url}, True)
        assert state["shot"]["type"] == "image_url"
        assert assets == {}

    def test_encode_images_assets(self):
        from midscene.core.ai_model.system_one import encode_system_one_images

        data_url = "data:image/jpeg;base64,BBBB"
        state, assets = encode_system_one_images({"shot": data_url}, False)
        assert state["shot"]  # reference id
        assert list(assets.values())[0]["format"] == "jpg"

    def test_resolve_endpoint(self):
        from midscene.core.ai_model.system_one import resolve_system_one_endpoint

        assert (
            resolve_system_one_endpoint({"openaiBaseURL": "https://x/v1/"})
            == "https://x/v1/systemone"
        )
        assert resolve_system_one_endpoint({"endpoint": "https://y"}) == "https://y"


# ---------------------------------------------------------------------------
# Jev workflows
# ---------------------------------------------------------------------------


class TestJevWorkflows:
    @pytest.mark.asyncio
    async def test_jev_locate(self):
        from midscene.core.ai_model.workflows.jev import jev_locate

        captured = {}

        async def fake_call_system_one(runtime, request):
            captured.update(request)
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "target": {
                        "type": "box",
                        "box": {"left": 0.25, "top": 0.25, "right": 0.75, "bottom": 0.75},
                    },
                },
            }

        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            result = await jev_locate(
                "the button",
                {"imageBase64": make_png_base64(), "width": 320, "height": 240},
                None,
            )
        # normalized 0-1 edges box on a 320x240 image
        assert result["locatedPixelResult"]["center"] == (160, 120)
        # upstream #3347: no presence pre-check, only the target box question
        assert set(captured["questions"]) == {"target"}
        assert captured["state"]["references"] == []

    @pytest.mark.asyncio
    async def test_jev_locate_returns_box_without_presence_check(self):
        from midscene.core.ai_model.workflows.jev import jev_locate

        async def fake_call_system_one(runtime, request):
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "target": {
                        "type": "box",
                        "box": {"left": 0.1, "top": 0.1, "right": 0.5, "bottom": 0.5},
                    },
                },
            }

        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            result = await jev_locate(
                "maybe missing",
                {"imageBase64": make_png_base64(), "width": 320, "height": 240},
                None,
            )
        assert "errors" not in result
        assert result["locatedPixelResult"]["center"] == (96, 72)

    @pytest.mark.asyncio
    async def test_jev_locate_with_reference_images(self):
        from midscene.core.ai_model.workflows.jev import jev_locate

        captured = {}

        async def fake_call_system_one(runtime, request):
            captured.update(request)
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "target": {
                        "type": "box",
                        "box": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0},
                    },
                },
            }

        png = make_png_base64()
        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            await jev_locate(
                {"prompt": "the button", "images": [{"name": "ref", "url": png}]},
                {"imageBase64": png, "width": 320, "height": 240},
                None,
            )
        assert captured["state"]["references"] == [
            {"image": "`reference_0`", "name": "ref"}
        ]
        assert "reference_0" in captured["images"]

    @pytest.mark.asyncio
    async def test_jev_locate_skips_reference_without_url(self):
        from midscene.core.ai_model.workflows.jev import jev_locate

        captured = {}

        async def fake_call_system_one(runtime, request):
            captured.update(request)
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "target": {
                        "type": "box",
                        "box": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0},
                    },
                },
            }

        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            await jev_locate(
                {"prompt": "the button", "images": [{"name": "broken"}]},
                {"imageBase64": make_png_base64(), "width": 320, "height": 240},
                None,
            )

        assert captured["state"]["references"] == []
        assert set(captured["images"]) == {"screenshot"}

    @pytest.mark.asyncio
    async def test_jev_locate_inlines_local_reference_path(self, tmp_path):
        from midscene.core.ai_model.workflows.jev import jev_locate

        captured = {}

        async def fake_call_system_one(runtime, request):
            captured.update(request)
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "target": {
                        "type": "box",
                        "box": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 1.0},
                    },
                },
            }

        reference = tmp_path / "ref.png"
        reference.write_bytes(base64.b64decode(make_png_base64()))
        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            await jev_locate(
                {"prompt": "the button", "images": [{"name": "ref", "url": str(reference)}]},
                {"imageBase64": make_png_base64(), "width": 320, "height": 240},
                None,
            )

        assert captured["state"]["references"] == [
            {"image": "`reference_0`", "name": "ref"}
        ]
        assert captured["images"]["reference_0"].startswith("data:image/png")

    @pytest.mark.asyncio
    async def test_jev_boolean(self):
        from midscene.core.ai_model.workflows.jev import jev_boolean

        async def fake_call_system_one(runtime, request):
            return {
                "content": "raw",
                "usage": {"total_tokens": 4},
                "answers": {"result": {"type": "noul", "noul": 0.8}},
            }

        with patch(
            "midscene.core.ai_model.workflows.jev.call_system_one",
            new=fake_call_system_one,
        ):
            class _Ctx:
                screenshot_base64 = make_png_base64()

            result = await jev_boolean("the page is loaded", _Ctx(), None)
        assert result["value"] is True


# ---------------------------------------------------------------------------
# Auto-GLM / UI-TARS planners
# ---------------------------------------------------------------------------


class TestAutoGlm:
    def test_parse_response_split(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_auto_glm_response,
        )

        response = parse_auto_glm_response(
            '<think>look around</think><answer>do(action="Tap", element=[123,456])</answer>'
        )
        # Upstream priority: the do(action=) branch wins over <answer>, and it
        # keeps both the <think> tags and the trailing </answer> (faithful).
        assert response["think"] == "<think>look around</think><answer>"
        assert response["content"] == 'do(action="Tap", element=[123,456])</answer>'

    def test_parse_tap_action(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {"think": "t", "content": 'do(action="Tap", element=[100,200])'}
        )
        assert action == {"_metadata": "do", "action": "Tap", "element": (100, 200), "think": "t"}

    def test_parse_finish_with_escaped_quotes(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {
                "think": "",
                "content": 'finish(message="Finished! There is a contact whose name is \\"Tom\\" in the list.")',
            }
        )
        assert action["_metadata"] == "finish"
        assert "Tom" in action["message"]

    def test_parse_wait_duration(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_auto_glm_planning_action,
        )

        action = parse_auto_glm_planning_action(
            {"think": "", "content": 'do(action="Wait", duration="3 seconds")'}
        )
        assert action["durationMs"] == 3000

    def test_transform_swipe_inverts_direction(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            transform_auto_glm_action,
        )

        def distance_to_pixels(delta, axis):
            return round(abs(delta))

        actions = transform_auto_glm_action(
            {
                "_metadata": "do",
                "action": "Swipe",
                "start": (500, 200),
                "end": (500, 800),
                "think": "swipe",
            },
            [],
            distance_to_pixels,
        )
        # finger moved down -> content scrolls -> direction 'up'
        assert actions[0]["type"] == "Scroll"
        assert actions[0]["param"]["direction"] == "up"
        assert actions[0]["param"]["distance"] == 600

    def test_transform_finish(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            transform_auto_glm_action,
        )

        actions = transform_auto_glm_action(
            {"_metadata": "finish", "message": "all done"}, [], None
        )
        assert actions[0]["type"] == "Finished"
        assert actions[0]["thought"] == "all done"

    def test_transform_unsupported_raises(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            transform_auto_glm_action,
        )

        with pytest.raises(ValueError) as exc:
            transform_auto_glm_action(
                {"_metadata": "do", "action": "Interact"}, [], None
            )
        assert "not supported" in str(exc.value)


class TestUiTars:
    def test_parse_action_call(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_ui_tars_action_calls,
        )

        raw = "Thought: click the button\nAction: click(start_box='[500,300,600,340]')"
        actions = parse_ui_tars_action_calls(raw)
        assert actions[0]["action_type"] == "click"
        # [500,300,600,340] / 1000 -> [0.5,0.3,0.6,0.34]
        box = json.loads(actions[0]["action_inputs"]["start_box"])
        assert box == pytest.approx([0.5, 0.3, 0.6, 0.34], abs=1e-6)
        assert actions[0]["thought"] == "click the button"

    def test_transform_click(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
        )

        parsed = {
            "actions": parse_ui_tars_action_calls(
                "Thought: tap it\nAction: click(start_box='[250,150]')"
            )
        }
        transformed, unhandled = transform_ui_tars_actions(parsed)
        assert unhandled == []
        assert transformed[0]["type"] == "Tap"
        point = transformed[0]["param"]["locate"]["point"]
        assert point == pytest.approx((0.25, 0.15), abs=1e-6)

    def test_transform_hotkey(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
            _transform_hotkey_input,
        )

        assert _transform_hotkey_input("ctrl a") == ["Control", "a"]
        assert _transform_hotkey_input("enter") == ["Enter"]

        parsed = {
            "actions": parse_ui_tars_action_calls(
                "Thought: submit\nAction: hotkey(key='Return')"
            )
        }
        transformed, _ = transform_ui_tars_actions(parsed)
        assert transformed[0]["type"] == "KeyboardPress"
        assert transformed[0]["param"]["keyName"] == "Enter"

    def test_transform_finished(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_ui_tars_action_calls,
            transform_ui_tars_actions,
        )

        parsed = {
            "actions": parse_ui_tars_action_calls(
                'Thought: done\nAction: finished(content="task completed")'
            )
        }
        transformed, _ = transform_ui_tars_actions(parsed)
        assert transformed[0]["type"] == "Finished"
        assert transformed[0]["thought"] == "task completed"

    def test_bbox_conversion(self):
        from midscene.core.ai_model.workflows.planning_custom import (
            parse_ui_tars_action_calls,
        )

        raw = "Action: click(start_box='<bbox>100 200 300 400</bbox>')"
        actions = parse_ui_tars_action_calls(raw)
        box = json.loads(actions[0]["action_inputs"]["start_box"])
        # center of (100,200)-(300,400) = (200,300) -> /1000
        assert box == pytest.approx([0.2, 0.3, 0.2, 0.3], abs=1e-6)


# ---------------------------------------------------------------------------
# DeepLocate
# ---------------------------------------------------------------------------


class TestDeepLocate:
    def test_expand_search_area(self):
        from midscene.core.ai_model.workflows.search_area import expand_search_area

        rect = {"left": 500, "top": 500, "width": 50, "height": 30}
        expanded = expand_search_area(rect, {"width": 1000, "height": 1000})
        assert expanded["width"] * expanded["height"] >= 400 * 400

    def test_expand_clamps_to_screen(self):
        from midscene.core.ai_model.workflows.search_area import expand_search_area

        rect = {"left": 0, "top": 0, "width": 900, "height": 900}
        expanded = expand_search_area(rect, {"width": 1000, "height": 1000})
        assert expanded["left"] == 0
        assert expanded["top"] == 0

    def test_mapping_roundtrip(self):
        from midscene.core.ai_model.workflows.search_area import (
            map_search_area_result_to_original_result,
        )

        mapping = {"offset": {"x": 100, "y": 50}, "scale": 2}
        result = map_search_area_result_to_original_result(
            {"center": (40, 60), "rect": {"left": 30, "top": 50, "width": 20, "height": 20}},
            mapping,
        )
        assert result["center"] == [120, 80]
        assert result["rect"]["left"] == 115

    @pytest.mark.asyncio
    async def test_two_stage_locate(self, mock_interface):
        """deepLocate with a plan coordinate hint: search-area crop + element
        locate on the zoomed image, then mapping back."""
        from midscene.core.ai_model.workflows.locate_service import locate_service

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
            "midscene.core.ai_model.workflows.locate_service.call_generative_ai",
            new=fake_call,
        ), patch(
            "midscene.core.ai_model.workflows.locate_service.ai_locate_element",
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


class TestLocatePromptOrder:
    def _input(self, references=None):
        return {
            "instructions": "rules",
            "screenshot": "screen",
            "task": "target",
            "references": references or [],
        }

    def test_default_keeps_trailing_references(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(), self._input([reference])
        ) == [
            {"role": "system", "content": "rules"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": "screen"},
                    {"type": "text", "text": "target"},
                ],
            },
            reference,
        ]

    def test_user_each_emits_separate_messages_and_skips_absent_references(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        for layout in (
            "userEach(screenshot:instructions:task:references)",
            "userEach(screenshot:instructions:references:task)",
        ):
            assert build_locate_messages(
                parse_locate_prompt_order(layout), self._input()
            ) == [
                {"role": "user", "content": [{"type": "image", "url": "screen"}]},
                {"role": "user", "content": "rules"},
                {"role": "user", "content": "target"},
            ]

    def test_preserves_reference_boundaries_in_the_middle(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(screenshot:references:instructions:task)"
            ),
            self._input([reference]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            reference,
            {"role": "user", "content": "rules"},
            {"role": "user", "content": "target"},
        ]

    def test_flattens_reference_blocks_and_keeps_group_boundaries(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        reference = {"role": "user", "content": "reference"}
        reference_image = {"role": "user", "content": [{"type": "image", "url": "ref"}]}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userTogether(screenshot):userTogether(instructions:references:task)"
            ),
            self._input([reference, reference_image]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "rules"},
                    {"type": "text", "text": "reference"},
                    {"type": "image", "url": "ref"},
                    {"type": "text", "text": "target"},
                ],
            },
        ]

    def test_skips_empty_references_only_group(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(instructions):userTogether(references):"
                "userTogether(task:screenshot)"
            ),
            self._input(),
        ) == [
            {"role": "user", "content": "rules"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "target"},
                    {"type": "image", "url": "screen"},
                ],
            },
        ]

    def test_system_can_hold_the_task(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        assert build_locate_messages(
            parse_locate_prompt_order(
                "system(task):userTogether(screenshot:instructions):"
                "userEach(references)"
            ),
            self._input(),
        ) == [
            {"role": "system", "content": "target"},
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": "screen"},
                    {"type": "text", "text": "rules"},
                ],
            },
        ]

    def test_preserves_text_order_and_system_positions(self):
        from midscene.core.ai_model.locate_prompt_order import (
            build_locate_messages,
            parse_locate_prompt_order,
        )

        for parts, content in (
            ("instructions:task", "rules\n\ntarget"),
            ("task:instructions", "target\n\nrules"),
        ):
            assert build_locate_messages(
                parse_locate_prompt_order(
                    f"system({parts}):userEach(screenshot:references)"
                ),
                self._input(),
            ) == [
                {"role": "system", "content": content},
                {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            ]

        reference = {"role": "user", "content": "reference"}
        assert build_locate_messages(
            parse_locate_prompt_order(
                "userEach(screenshot):system(task):userEach(references):"
                "system(instructions)"
            ),
            self._input([reference]),
        ) == [
            {"role": "user", "content": [{"type": "image", "url": "screen"}]},
            {"role": "system", "content": "target"},
            reference,
            {"role": "system", "content": "rules"},
        ]

    @pytest.mark.parametrize("part", ["screenshot", "references"])
    def test_rejects_image_parts_in_system(self, part):
        from midscene.core.ai_model.locate_prompt_order import (
            parse_locate_prompt_order,
        )

        with pytest.raises(
            ValueError, match=f'system cannot contain image part "{part}"'
        ):
            parse_locate_prompt_order(f"system({part}):userEach(instructions:task)")

    @pytest.mark.parametrize(
        "order",
        [
            "userEach(screenshot):userTogether(task:references:screenshot)",
            "system(task):userEach(instructions:task:screenshot:references)",
            "system(instructions):system(instructions):"
            "userEach(task:screenshot:references)",
            "system():userEach(instructions:task:screenshot:references)",
            "userEach():userTogether(instructions:task:references:screenshot)",
            "userEach(screenshot:task:references)",
            "userEach(instructions:task:references:task)",
            "userEach(instructions:screenshot:task:other)",
        ],
    )
    def test_rejects_invalid_orders(self, order):
        from midscene.core.ai_model.locate_prompt_order import (
            parse_locate_prompt_order,
        )

        with pytest.raises(ValueError, match="Invalid locate promptOrder"):
            parse_locate_prompt_order(order)

    @pytest.mark.asyncio
    async def test_element_locate_respects_prompt_order(self, mock_interface):
        from midscene.core.ai_model.adapters import ModelAdapter, ModelRuntime
        from midscene.core.ai_model.workflows import ai_locate_element

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [100, 100, 199, 199]}', "usage": None}

        adapter = ModelAdapter(
            "test-prompt-first",
            locate_prompt_order=(
                "system(instructions):userEach(task:screenshot:references)"
            ),
        )
        runtime = ModelRuntime(
            {
                "modelName": "mock-model",
                "modelFamily": "qwen2.5-vl",
                "retryCount": 0,
                "retryInterval": 0,
            },
            adapter,
        )
        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_element("the Submit button", context, runtime)

        messages = captured["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "user",
        ]
        assert "the Submit button" in messages[1]["content"]
        assert messages[2]["content"][0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_section_locate_respects_prompt_order(self, mock_interface):
        from midscene.core.ai_model.adapters import ModelAdapter, ModelRuntime
        from midscene.core.ai_model.workflows.locate_service import (
            ai_locate_section,
        )

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [0, 0, 500, 500]}', "usage": None}

        adapter = ModelAdapter(
            "test-prompt-first",
            locate_prompt_order=(
                "system(instructions):userEach(task:screenshot:references)"
            ),
        )
        runtime = ModelRuntime(
            {
                "modelName": "mock-model",
                "modelFamily": "gpt-5",
                "retryCount": 0,
                "retryInterval": 0,
            },
            adapter,
        )
        with patch_model_call(
            "midscene.core.ai_model.workflows.locate_service", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_section(context, "the row containing Apollo", runtime)

        messages = captured["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "user",
        ]
        assert "the row containing Apollo" in messages[1]["content"]
        assert messages[2]["content"][0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_element_locate_appends_reference_images(self, mock_interface):
        from midscene.core.ai_model.workflows import ai_locate_element

        captured = {}

        async def handler(messages, runtime, options=None):
            captured["messages"] = messages
            return {"content": '{"bbox": [100, 100, 199, 199]}', "usage": None}

        png = "data:image/png;base64," + make_png_base64()
        with patch_model_call(
            "midscene.core.ai_model.workflows.grounding", handler
        ):
            context = await mock_interface.get_context()
            await ai_locate_element(
                {
                    "prompt": "the Submit button",
                    "images": [{"name": "ref", "url": png}],
                },
                context,
                _make_runtime(modelFamily="qwen2.5-vl"),
            )

        messages = captured["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        reference_messages = messages[2:]
        assert "reference images" in reference_messages[0]["content"][0]["text"]
        assert "named 'ref'" in reference_messages[1]["content"][0]["text"]
        assert reference_messages[2]["content"][0] == {
            "type": "image",
            "url": png,
        }


def _make_runtime(**overrides):
    from midscene.core.ai_model.adapters import get_model_runtime

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


# ---------------------------------------------------------------------------
# Model fallback
# ---------------------------------------------------------------------------


class TestModelFallback:
    def test_jev_extracts_fall_back_to_default(self):
        from midscene.core.ai_model.adapters import resolve_model_for_task_type

        configs = {
            "locate": {"modelName": "jev-1", "modelFamily": "jev", "intent": "locate", "slot": "locate"},
            "insight": {"modelName": "jev-1", "modelFamily": "jev", "intent": "insight", "slot": "insight"},
            "planning": {"modelName": "jev-1", "modelFamily": "jev", "intent": "planning", "slot": "planning"},
            "default": {"modelName": "doubao", "modelFamily": "doubao-seed", "intent": "default", "slot": "default"},
        }
        runtime = resolve_model_for_task_type(
            lambda intent: configs[intent], "insight", "extract"
        )
        assert runtime.model_fallback is not None
        assert runtime.adapter.family == "doubao-seed"

        # jev can serve locate/boolean/planning directly
        runtime = resolve_model_for_task_type(
            lambda intent: configs[intent], "locate", "locate"
        )
        assert runtime.model_fallback is None


# ---------------------------------------------------------------------------
# YAML runner
# ---------------------------------------------------------------------------


class TestYamlRunner:
    def test_parse_script(self):
        from midscene.core.yaml_runner import parse_yaml_script

        script = parse_yaml_script(
            """
web:
  url: https://example.com
tasks:
  - name: flow
    flow:
      - aiAction: click the button
      - sleep: 100
"""
        )
        assert script["web"]["url"] == "https://example.com"
        assert script["tasks"][0]["flow"][0]["aiAction"] == "click the button"

    def test_parse_requires_tasks(self):
        from midscene.core.yaml_runner import parse_yaml_script

        with pytest.raises(ValueError) as exc:
            parse_yaml_script("web:\n  url: https://example.com\n")
        assert '"tasks" is required' in str(exc.value)

    def test_computer_env_is_a_target(self):
        from midscene.core.yaml_runner import parse_yaml_script

        script = parse_yaml_script(
            "computer:\n  displayId: '1'\n"
            "tasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
        )
        assert script["computer"]["displayId"] == "1"

    def test_computer_and_web_are_mutually_exclusive(self):
        from midscene.core.yaml_runner import parse_yaml_script

        with pytest.raises(ValueError, match="only one of"):
            parse_yaml_script(
                "web:\n  url: https://example.com\ncomputer: {}\n"
                "tasks:\n  - name: t\n    flow:\n      - sleep: 1\n"
            )

    def test_env_interpolation(self):
        from midscene.core.yaml_runner import parse_yaml_script

        import os

        os.environ["MIDSCENE_TEST_URL"] = "https://env-example.com"
        script = parse_yaml_script(
            """
web:
  url: ${MIDSCENE_TEST_URL}
tasks:
  - name: t
    flow:
      - sleep: 10
"""
        )
        assert script["web"]["url"] == "https://env-example.com"

    def test_env_interpolation_inside_tasks(self, monkeypatch):
        from midscene.core.yaml_runner import parse_yaml_script

        monkeypatch.setenv("TASK_NAME", "hello")
        script = parse_yaml_script(
            "tasks:\n"
            "  - name: ${TASK_NAME}\n"
            "    flow:\n"
            "      - sleep: 10\n"
        )
        assert script["tasks"][0]["name"] == "hello"

    def test_env_interpolation_keeps_unresolved_refs_in_tasks(self, monkeypatch):
        from midscene.core.yaml_runner import parse_yaml_script

        monkeypatch.delenv("NOT_DEFINED_VAR", raising=False)
        script = parse_yaml_script(
            "tasks:\n"
            "  - name: ${NOT_DEFINED_VAR}\n"
            "    flow:\n"
            "      - sleep: 10\n"
        )
        assert script["tasks"][0]["name"] == "${NOT_DEFINED_VAR}"

    def test_env_interpolation_missing_outside_tasks_raises(self, monkeypatch):
        from midscene.core.yaml_runner import parse_yaml_script

        monkeypatch.delenv("NOT_DEFINED_VAR", raising=False)
        with pytest.raises(ValueError, match="NOT_DEFINED_VAR"):
            parse_yaml_script(
                "web:\n  url: ${NOT_DEFINED_VAR}\ntasks: []\n"
            )

    @pytest.mark.asyncio
    async def test_player_runs_flow(self):
        from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

        script = parse_yaml_script(
            """
tasks:
  - name: t
    flow:
      - aiTap: the test button
      - aiInput:
          locate: the username field
          value: hello
      - sleep: 1
"""
        )
        interface = MockInterface()

        async def fake_locate(locate_param):
            return {"center": (10, 10), "rect": None, "description": "x"}

        agent = _make_agent(interface)
        with patch.object(agent, "_locate_for_action", fake_locate):
            player = ScriptPlayer(script, agent)
            await player.run()

        assert player.status == "done"
        # aiTap + aiInput (Input taps the field first, then types)
        assert interface.tapped == [(10, 10), (10, 10)]
        assert interface.typed == ["hello"]


def _make_agent(interface):
    from midscene.core.agent import Agent
    from midscene.core.types import AgentOptions

    return Agent(
        interface,
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "mock-model",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            }
        ),
    )


# ---------------------------------------------------------------------------
# Dump structure
# ---------------------------------------------------------------------------


class TestDump:
    def test_report_dump_structure(self):
        from midscene.core.dump import ExecutionDumpBuilder, build_execution_task, build_service_dump

        builder = ExecutionDumpBuilder(group_name="g", device_type="web")
        service_dump = build_service_dump(
            "locate",
            {"element": "the button"},
            None,
            {"durationMs": 12, "rawResponse": "r", "usage": {"total_tokens": 5}},
            matched_element=[{"center": [1, 2]}],
            deep_locate=True,
        )
        task = build_execution_task("Insight", "Locate", {"prompt": "the button"}, log=service_dump)
        builder.add_execution("Tap - the button", [task])
        dump = builder.to_dict()

        assert dump["sdkVersion"]
        assert dump["groupName"] == "g"
        assert dump["deviceType"] == "web"
        execution = dump["executions"][0]
        assert execution["name"] == "Tap - the button"
        assert execution["tasks"][0]["type"] == "Insight"
        assert execution["tasks"][0]["subType"] == "Locate"
        assert execution["tasks"][0]["log"]["type"] == "locate"
        assert execution["tasks"][0]["log"]["deepLocate"] is True

    def test_dump_writes_to_disk(self, tmp_path, monkeypatch):
        from midscene.core.dump import ExecutionDumpBuilder, build_execution_task

        monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
        builder = ExecutionDumpBuilder(group_name="g")
        builder.add_execution("Sleep", [build_execution_task("Action Space", "Sleep", {"timeMs": 1})])
        path = builder.write_to_disk("unit-dump")
        assert path
        content = json.loads(open(path).read())
        assert content["executions"][0]["tasks"][0]["subType"] == "Sleep"


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


class TestConnectivity:
    @pytest.mark.asyncio
    async def test_text_check_passes_on_token(self):
        from midscene.core.ai_model.connectivity import _run_check, _text_check

        async def fake_call(messages, runtime, options=None):
            return {"content": "CONNECTIVITY_OK", "usage": None}

        with patch(
            "midscene.core.ai_model.connectivity.call_generative_ai",
            new=fake_call,
        ):
            result = await _run_check(
                "text", "planning", {"modelName": "m"}, _text_check
            )
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_text_check_fails_on_wrong_token(self):
        from midscene.core.ai_model.connectivity import _run_check, _text_check

        async def fake_call(messages, runtime, options=None):
            return {"content": "HELLO", "usage": None}

        with patch(
            "midscene.core.ai_model.connectivity.call_generative_ai",
            new=fake_call,
        ):
            result = await _run_check(
                "text", "planning", {"modelName": "m"}, _text_check
            )
        assert result["passed"] is False
        assert "Unexpected response" in result["message"]

    @pytest.mark.asyncio
    async def test_full_test_aggregates(self):
        from midscene.core.ai_model.connectivity import run_connectivity_test

        async def fake_call(messages, runtime, options=None):
            return {"content": "CONNECTIVITY_OK", "usage": None}

        config = {
            "defaultModelConfig": {"modelName": "m"},
            "planningModelConfig": {"modelName": "m"},
            "insightModelConfig": {"modelName": "m"},
        }
        with patch(
            "midscene.core.ai_model.connectivity.call_generative_ai",
            new=fake_call,
        ), patch(
            "midscene.core.ai_model.connectivity._vision_check",
            new=AsyncMock(return_value={"passed": True, "content": ""}),
        ), patch(
            "midscene.core.ai_model.connectivity._ai_locate_check",
            new=AsyncMock(return_value={"passed": True, "content": ""}),
        ):
            result = await run_connectivity_test(config)
        assert result["passed"] is True
        assert len(result["checks"]) == 4


# ---------------------------------------------------------------------------
# SIWC
# ---------------------------------------------------------------------------


class TestSiwc:
    def test_authorization_url_contains_pkce(self):
        from midscene.core.ai_model.siwc import create_siwc_authorization

        auth = create_siwc_authorization(
            "urn:uuid:test", "http://127.0.0.1:9999/auth/callback"
        )
        assert "code_challenge_method=S256" in auth["url"]
        assert "chatgpt.tokens.use.direct" in auth["url"]

    def test_parse_callback_validates_state(self):
        from midscene.core.ai_model.siwc import (
            create_siwc_authorization,
            parse_siwc_callback,
        )

        auth = create_siwc_authorization(
            "urn:uuid:test", "http://127.0.0.1:9999/auth/callback"
        )
        attempt = auth["attempt"]
        callback_url = (
            "http://127.0.0.1:9999/auth/callback"
            f"?code=abc&client_id=client-1&state={attempt['state']}"
        )
        parsed = parse_siwc_callback(callback_url, attempt)
        assert parsed == {"code": "abc", "client_id": "client-1"}

        # state mismatch -> undefined (no raise), like upstream
        assert (
            parse_siwc_callback(
                "http://127.0.0.1:9999/auth/callback?code=abc&client_id=client-1&state=wrong",
                attempt,
            )
            is None
        )

    def test_parse_callback_rejects_dynamic_client(self):
        from midscene.core.ai_model.siwc import (
            create_siwc_authorization,
            parse_siwc_callback,
        )

        auth = create_siwc_authorization(
            "urn:uuid:test", "http://127.0.0.1:9999/auth/callback"
        )
        attempt = auth["attempt"]
        callback_url = (
            "http://127.0.0.1:9999/auth/callback"
            f"?code=abc&client_id=dynamic_agent_client&state={attempt['state']}"
        )
        with pytest.raises(Exception):
            parse_siwc_callback(callback_url, attempt)

    def test_resolve_proxy_precedence(self, monkeypatch):
        from midscene.core.ai_model.siwc import _siwc_proxy

        # Explicit config wins over the environment; HTTP beats SOCKS.
        monkeypatch.setenv("MIDSCENE_MODEL_HTTP_PROXY", "http://env:8080")
        monkeypatch.setenv("MIDSCENE_MODEL_SOCKS_PROXY", "socks5://env:1080")
        assert (
            _siwc_proxy({"httpProxy": "http://explicit:1", "socksProxy": None})
            == "http://explicit:1"
        )
        assert _siwc_proxy({"httpProxy": None, "socksProxy": "socks5://s:2"}) == (
            "socks5://s:2"
        )
        # An explicit (even empty) config disables the env fallback, like upstream.
        assert _siwc_proxy({}) is None
        # No config at all resolves from the environment.
        assert _siwc_proxy() == "http://env:8080"
        monkeypatch.setenv("MIDSCENE_MODEL_HTTP_PROXY", "  ")
        assert _siwc_proxy() == "socks5://env:1080"

    @pytest.mark.asyncio
    async def test_refresh_request_uses_configured_proxy(self):
        from midscene.core.ai_model import siwc

        captured: Dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse(
                    {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "chatgpt.tokens.use.direct",
                    }
                )

        with patch.object(siwc.httpx, "AsyncClient", _Client):
            refreshed = await siwc.refresh_siwc_credentials(
                {
                    "client_id": "client-1",
                    "refresh_token": "refresh-1",
                    "subject": "subject-1",
                },
                {"httpProxy": "http://proxy:8080", "socksProxy": None},
            )

        assert captured["proxy"] == "http://proxy:8080"
        assert refreshed["access_token"] == "new-access"

    @pytest.mark.asyncio
    async def test_refresh_request_falls_back_to_env_proxy(self, monkeypatch):
        from midscene.core.ai_model import siwc

        monkeypatch.setenv("MIDSCENE_MODEL_HTTP_PROXY", "http://env:8080")
        monkeypatch.delenv("MIDSCENE_MODEL_SOCKS_PROXY", raising=False)
        captured: Dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse(
                    {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "chatgpt.tokens.use.direct",
                    }
                )

        with patch.object(siwc.httpx, "AsyncClient", _Client):
            await siwc.refresh_siwc_credentials(
                {"client_id": "client-1", "refresh_token": "refresh-1"}
            )

        assert captured["proxy"] == "http://env:8080"

    @pytest.mark.asyncio
    async def test_jwks_fetched_once_and_reused(self, monkeypatch):
        from midscene.core.ai_model import siwc

        calls = []
        keys = [object()]

        async def fake_fetch(proxy=None):
            calls.append(proxy)
            return keys

        monkeypatch.setattr(siwc, "_fetch_jwks", fake_fetch)
        monkeypatch.setattr(siwc, "_jwks_cache", None)
        assert await siwc._load_jwks(None) == keys
        # Cached keys are proxy-independent, so the second load is free.
        assert await siwc._load_jwks({"httpProxy": "http://proxy:8080"}) == keys
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_jwks_force_refetch_replaces_cache(self, monkeypatch):
        from midscene.core.ai_model import siwc

        rotated = [object(), object()]
        calls = []

        async def fake_fetch(proxy=None):
            calls.append(proxy)
            return rotated if len(calls) > 1 else [rotated[0]]

        monkeypatch.setattr(siwc, "_fetch_jwks", fake_fetch)
        monkeypatch.setattr(siwc, "_jwks_cache", None)
        assert await siwc._load_jwks(None) == [rotated[0]]
        assert await siwc._load_jwks(None, force=True) == rotated
        assert await siwc._load_jwks(None) == rotated
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_token_manager_threads_proxy_into_refresh(self):
        from midscene.core.ai_model import siwc

        record = {
            "credentials": {
                "access_token": "old",
                "client_id": "client-1",
                "refresh_token": "refresh-1",
            }
        }
        refresh = AsyncMock(return_value={**record["credentials"], "access_token": "new"})
        manager = siwc.SiwcTokenManager()
        proxy = {"httpProxy": "http://proxy:8080", "socksProxy": None}

        with patch.object(siwc, "_read_credentials", lambda: record), patch.object(
            siwc, "_save_credentials", lambda _record: None
        ), patch.object(siwc, "refresh_siwc_credentials", refresh):
            token = await manager.refresh_access_token("old", proxy)

        assert token == "new"
        refresh.assert_awaited_once_with(record["credentials"], proxy)

    @pytest.mark.asyncio
    async def test_exchange_uses_configured_proxy(self):
        from midscene.core.ai_model import siwc

        captured: Dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse(
                    {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "id_token": "id-token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "chatgpt.tokens.use.direct",
                    }
                )

        attempt = {
            "host_id": "urn:uuid:host",
            "redirect_uri": "http://127.0.0.1:9999/auth/callback",
            "nonce": "nonce-1",
            "verifier": "verifier-1",
        }
        verify = AsyncMock(
            return_value={"sub": "subject-1", "nonce": "nonce-1", "email": "a@b.c"}
        )
        with patch.object(siwc.httpx, "AsyncClient", _Client), patch.object(
            siwc, "_verify_id_token", verify
        ):
            credentials = await siwc.exchange_siwc_code(
                attempt,
                {"code": "code-1", "client_id": "client-1"},
                {"httpProxy": "http://proxy:8080", "socksProxy": None},
            )

        assert captured["proxy"] == "http://proxy:8080"
        assert credentials["subject"] == "subject-1"

    def test_public_entry_reexports_existing_implementation(self):
        import midscene.siwc as public
        from midscene.core.ai_model import siwc as internals

        assert public.refresh_siwc_credentials is internals.refresh_siwc_credentials
        assert public.create_siwc_authorization is internals.create_siwc_authorization
        assert public.exchange_siwc_code is internals.exchange_siwc_code
        assert public.parse_siwc_callback is internals.parse_siwc_callback
        error = public.SiwcError("fixture")
        assert type(error).__name__ == "SiwcError"
        assert isinstance(error, internals.SiwcError)


# ---------------------------------------------------------------------------
# Caller / adapter / prompt parity regressions
# ---------------------------------------------------------------------------


def _chat_completion_payload(content: str = "ok") -> Dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "model": "mock-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


class _StubAsyncClient:
    def __init__(self, responses):
        self._responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        return next(self._responses)


class TestCallerParity:
    @pytest.mark.asyncio
    async def test_siwc_token_expired_refreshes_once(self):
        from midscene.core.ai_model import caller
        from midscene.core.ai_model.adapters import get_model_runtime

        responses = iter(
            [
                FakeResponse({"error": {"code": "token_expired"}}, status_code=401),
                FakeResponse(_chat_completion_payload()),
            ]
        )
        refresh = AsyncMock(return_value="new-token")

        with patch.object(
            caller.httpx, "AsyncClient", lambda *a, **k: _StubAsyncClient(responses)
        ), patch.object(caller.siwc_token_manager, "refresh_access_token", refresh):
            runtime = get_model_runtime(
                {
                    "modelName": "mock-model",
                    "openaiApiKey": "old-token",
                    "httpProxy": "http://model-proxy:3128",
                    "retryCount": 0,
                    "retryInterval": 0,
                }
            )
            result = await caller.call_generative_ai(
                [{"role": "user", "content": "hi"}], runtime, {}
            )

        assert result["content"] == "ok"
        refresh.assert_awaited_once_with(
            "old-token",
            {"httpProxy": "http://model-proxy:3128", "socksProxy": None},
        )

    @pytest.mark.asyncio
    async def test_timeout_passed_to_httpx_in_seconds(self):
        from midscene.core.ai_model import caller

        captured: List[Dict[str, Any]] = []

        class RecordingClient(_StubAsyncClient):
            def __init__(self, *args, **kwargs):
                captured.append(kwargs)
                super().__init__([FakeResponse(_chat_completion_payload())])

        with patch.object(
            caller.httpx,
            "AsyncClient",
            lambda *a, **k: RecordingClient(*a, **k),
        ):
            await caller._post_json(
                url="https://example.com/v1/chat/completions",
                headers={},
                request_body={"model": "m", "messages": []},
                effective_timeout=5000,
                proxy=None,
                stream=False,
            )

        assert captured[0]["timeout"].read == 5.0

    def test_default_timeout_is_180s(self):
        from midscene.core.ai_model.caller import resolve_effective_timeout_ms

        assert resolve_effective_timeout_ms(None) == 180_000.0
        assert resolve_effective_timeout_ms(0) is None
        assert resolve_effective_timeout_ms(2500) == 2500.0

    def test_semantic_retry_temperature(self):
        from midscene.core.ai_model.adapters import get_model_runtime
        from midscene.core.ai_model.caller import prepare_chat_completion

        runtime = get_model_runtime(
            {
                "modelName": "mock-model",
                "responseFormat": "none",
            }
        )
        first = prepare_chat_completion(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert first["request_body"]["temperature"] == 0.0

        retry = prepare_chat_completion(
            [{"role": "user", "content": "hi"}],
            runtime,
            {"semanticRetryAttempt": 1},
        )
        assert retry["request_body"]["temperature"] == 0.2


class TestAdapterParity:
    def test_gpt5_responses_json_mode_only_when_expected(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        adapter = get_model_adapter("gpt-5")
        params = adapter.build_responses_params(
            {}, {"responseFormat": "json_object"}, True
        )
        assert params["text"] == {"format": {"type": "json_object"}}

        params = adapter.build_responses_params(
            {}, {"responseFormat": "json_object"}, False
        )
        assert "text" not in params

    def test_deep_locate_support_flags(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        assert get_model_adapter("gpt-5").supports_action_deep_locate is True
        assert get_model_adapter("auto-glm").supports_action_deep_locate is False
        assert get_model_adapter("vlm-ui-tars").supports_action_deep_locate is False

    def test_kimi3_replays_raw_assistant_message(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        assert get_model_adapter("kimi3").replay_raw_assistant_message is True
        assert get_model_adapter("gpt-5").replay_raw_assistant_message is False

    def test_new_family_locate_formats(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        step = get_model_adapter("step").locate_result_codec.prompt_spec
        assert step["resultKey"] == "point_2d"
        assert step["resultKeyAliases"] == ["point"]

        tencent = get_model_adapter("tencent-hy").locate_result_codec.prompt_spec
        assert tencent["resultKey"] == "box_2d"
        assert tencent["resultValueSchema"] == "[number, number, number, number]"

        qwen4 = get_model_adapter("qwen4").locate_result_codec.prompt_spec
        assert qwen4["resultKey"] == "point"
        assert qwen4["resultKeyAliases"] == ["point_2d"]

    def test_openrouter_reasoning_shapes(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        params = get_model_adapter("qwen4").build_chat_completion_params(
            {}, {"reasoningEnabled": True, "reasoningBudget": 64}
        )
        assert params["enable_thinking"] is True
        assert params["thinking_budget"] == 64

        openrouter = {
            "baseURL": "https://openrouter.ai/api/v1",
            "reasoningEnabled": True,
            "reasoningEffort": "high",
            "reasoningBudget": 64,
        }
        params = get_model_adapter("qwen4").build_chat_completion_params(
            {}, openrouter
        )
        assert params["reasoning"] == {
            "enabled": True,
            "effort": "high",
            "max_tokens": 64,
        }
        assert "enable_thinking" not in params

        disabled = get_model_adapter("qwen4").build_chat_completion_params(
            {}, {"baseURL": "https://openrouter.ai/api/v1", "reasoningEnabled": False}
        )
        assert disabled["reasoning"] == {"enabled": False}

        step = get_model_adapter("step").build_chat_completion_params(
            {},
            {
                "baseURL": "https://openrouter.ai/api/v1",
                "reasoningEnabled": False,
            },
        )
        assert step["reasoning"] == {"effort": "low"}

        # The URL match is exact; a trailing slash is not OpenRouter.
        native = get_model_adapter("qwen4").build_chat_completion_params(
            {},
            {
                "baseURL": "https://openrouter.ai/api/v1/",
                "reasoningEnabled": True,
            },
        )
        assert "reasoning" not in native
        assert native["enable_thinking"] is True

    def test_reasoning_effort_only_when_enabled(self):
        from midscene.core.ai_model.adapters import get_model_adapter

        for family in ("kimi3", "deepseek", "doubao-seed"):
            params = get_model_adapter(family).build_chat_completion_params(
                {}, {"reasoningEnabled": False, "reasoningEffort": "high"}
            )
            assert "reasoning_effort" not in params, family

        params = get_model_adapter("kimi3").build_chat_completion_params(
            {}, {"reasoningEnabled": True, "reasoningEffort": "high"}
        )
        assert params["reasoning_effort"] == "high"
        assert params["thinking"] == {"type": "enabled"}

        # "default" leaves native thinking untouched.
        params = get_model_adapter("glm-v").build_chat_completion_params(
            {}, {"reasoningEnabled": "default"}
        )
        assert "thinking" not in params

    def test_qwen_single_item_array_unwrap_only_for_locate(self):
        from midscene.core.ai_model.adapters import get_model_adapter
        from midscene.core.ai_model.json_utils import parse_model_response_json

        adapter = get_model_adapter("qwen3")
        raw = '[{"bbox_2d":[562,653,574,671],"label":"Approve checkbox"}]'
        parsed = adapter.json_parser(raw, "locate")
        assert parsed == {"bbox_2d": [562, 653, 574, 671], "label": "Approve checkbox"}

        parsed = adapter.json_parser(raw, "generic-object")
        assert isinstance(parsed, list)
        assert parse_model_response_json(raw) == [
            {"bbox_2d": [562, 653, 574, 671], "label": "Approve checkbox"}
        ]

        element = adapter.locate_protocol["element"]["parse_raw_response"](
            raw, adapter.locate_result_codec.prompt_spec
        )
        assert element["kind"] == "located"
        assert element["target"] == [562, 653, 574, 671]

    def test_unset_temperature_removed_from_request(self):
        from midscene.core.ai_model import caller
        from midscene.core.ai_model.adapters import get_model_runtime

        runtime = get_model_runtime(
            {
                "modelName": "mock-model",
                "modelFamily": "gpt-5",
                "temperature": "unset",
                "retryCount": 0,
            }
        )
        chat = caller.prepare_chat_completion(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert "temperature" not in chat["request_body"]

        responses = caller.prepare_responses(
            [{"role": "user", "content": "hi"}], runtime, {}
        )
        assert "temperature" not in responses["request_body"]


class TestPromptParity:
    def test_data_demand_keeps_cjk(self):
        from midscene.core.ai_model.prompts.insight import extract_data_query_prompt

        prompt = extract_data_query_prompt("页面", {"标题": "string"})
        assert "标题" in prompt
        assert "\\u" not in prompt

    def test_typed_demand_values(self):
        from midscene.core.ai_model.prompts.insight import (
            build_type_query_demand_value,
        )

        assert build_type_query_demand_value("Assert", "登录成功").startswith(
            "Boolean, based on the current screenshot"
        )
        assert "wait for" in build_type_query_demand_value("WaitFor", "加载完成")
        assert build_type_query_demand_value("Number", "count").startswith("Number, ")

    def test_multiline_action_space_uses_literal_blocks(self):
        from midscene.core.ai_model.prompts.planning import (
            serialize_action_descriptions,
        )

        dumped = serialize_action_descriptions([{"description": "line one\nline two"}])
        assert "|-\n" in dumped
        assert "\\n" not in dumped

    def test_distance_fields_include_input_image_unit_note(self):
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
        assert (
            "Use pixels of the input image for this distance, even when "
            "position coordinates are normalized." in prompt
        )

    @pytest.mark.asyncio
    async def test_scroll_executor_passes_distance_unchanged(self):
        from midscene.core.actions import _execute_scroll
        from tests.test_core import MockInterface

        interface = MockInterface()
        await _execute_scroll({"direction": "down", "distance": 123}, interface, None)
        assert interface.scrolled[-1][1] == 123


class TestTypedQueryParity:
    @pytest.mark.asyncio
    async def test_boolean_query_uses_type_key(self):
        calls: List[Any] = []

        async def handler(*args, **kwargs):
            calls.append(args[0])
            return {
                "content": '<data-json>{"Boolean": true}</data-json>',
                "usage": None,
            }

        agent = _make_agent(MockInterface())
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight", handler
        ):
            assert await agent.ai_boolean("is loaded") is True

        assert "Boolean, based on the current screenshot" in json.dumps(
            calls[0], ensure_ascii=False
        )

    @pytest.mark.asyncio
    async def test_wait_for_uses_statement_key(self):
        calls: List[Any] = []

        async def handler(*args, **kwargs):
            calls.append(args[0])
            return {
                "content": '<data-json>{"StatementIsTruthy": true}</data-json>',
                "usage": None,
            }

        agent = _make_agent(MockInterface())
        with patch_model_call(
            "midscene.core.ai_model.workflows.insight", handler
        ):
            await agent.ai_wait_for("loaded", {"timeoutMs": 100, "checkIntervalMs": 10})

        assert "the user wants to do some 'wait for' operation" in json.dumps(
            calls[0], ensure_ascii=False
        )


class TestPlanningLocateNormalization:
    def _codec(self):
        from midscene.core.ai_model.adapters import GPT_LOCATE_FORMAT
        from midscene.core.ai_model.locate_result import create_locate_result_codec

        return create_locate_result_codec(GPT_LOCATE_FORMAT)

    def test_prompt_only_when_not_included(self):
        from midscene.core.ai_model.workflows.planning import (
            normalize_planning_locate_parameter,
        )

        normalized = normalize_planning_locate_parameter(
            {"prompt": "button", "bbox": [1, 2, 3, 4]},
            self._codec(),
            {"preparedSize": {"width": 320, "height": 240}},
            False,
        )
        assert normalized == {"prompt": "button"}

    def test_coordinates_are_converted_and_removed(self):
        from midscene.core.ai_model.workflows.planning import (
            normalize_planning_locate_parameter,
        )

        normalized = normalize_planning_locate_parameter(
            {"prompt": "button", "bbox": [190, 115, 210, 135]},
            self._codec(),
            {"preparedSize": {"width": 320, "height": 240}},
            True,
        )
        assert "bbox" not in normalized
        assert normalized["locatedPixelResult"]["center"] == (200.0, 125.0)

    def test_missing_coordinates_raise(self):
        from midscene.core.ai_model.workflows.planning import (
            normalize_planning_locate_parameter,
        )

        with pytest.raises(ValueError):
            normalize_planning_locate_parameter(
                {"prompt": "button"},
                self._codec(),
                {"preparedSize": {"width": 320, "height": 240}},
                True,
            )


class TestActionSpaceParity:
    def test_actions_require_device_primitives(self):
        class TapOnlyInterface:
            interface_type = "web"

            async def tap(self, x, y):
                pass

        names = {action.name for action in _make_agent(TapOnlyInterface()).action_space}
        assert "Tap" in names
        assert "RightClick" not in names
        assert "MiddleClick" not in names
        assert "Scroll" not in names

    def test_android_action_space(self):
        from midscene.core.actions import build_android_action_space

        names = {action.name for action in build_android_action_space()}
        assert {
            "Tap",
            "Swipe",
            "LongPress",
            "DragAndDrop",
            "AndroidBackButton",
            "AndroidHomeButton",
            "AndroidRecentAppsButton",
        } <= names

    def test_scroll_action_descriptions_match_upstream(self):
        from midscene.core.actions import build_android_action_space

        scroll = next(
            action
            for action in build_android_action_space()
            if action.name == "Scroll"
        )
        assert "browse content outside the current viewport" in scroll.description
        assert "scrollToBottom/scrollToTop" in scroll.description
        locate_description = scroll.param_schema["locate"]["description"]
        assert (
            'Do NOT provide a general intent like "scroll to find some element"'
            in locate_description
        )
        assert (
            "screen-coordinate units"
            in scroll.param_schema["distance"]["description"]
        )
        assert (
            "Only effective when scrollType"
            in scroll.param_schema["direction"]["description"]
        )

    @pytest.mark.asyncio
    async def test_scroll_drops_unsupported_kwargs(self):
        from midscene.core.actions import _execute_scroll

        class ScrollDevice:
            def __init__(self):
                self.calls = []

            async def scroll(self, direction, distance=None):
                self.calls.append((direction, distance))

        device = ScrollDevice()
        await _execute_scroll(
            {"direction": "down", "scrollType": "scrollToBottom", "distance": 120},
            device,
            None,
        )
        assert device.calls == [("down", 120)]

    @pytest.mark.asyncio
    async def test_scroll_passes_located_point(self):
        from midscene.core.actions import _execute_scroll

        class ScrollDevice:
            def __init__(self):
                self.calls = []

            async def scroll(
                self, direction, distance=None, point=None, scroll_type=None
            ):
                self.calls.append((direction, distance, point, scroll_type))

        async def locate_fn(param):
            return {"center": [10, 20]}

        device = ScrollDevice()
        await _execute_scroll(
            {"direction": "down", "locate": {"prompt": "the product list"}},
            device,
            locate_fn,
        )
        assert device.calls == [("down", None, [10, 20], "singleAction")]

    @pytest.mark.asyncio
    async def test_input_drops_unsupported_options(self):
        from midscene.core.actions import _execute_input

        class InputDevice:
            def __init__(self):
                self.typed = None

            async def input_text(self, text):
                self.typed = text

        device = InputDevice()
        await _execute_input(
            {"value": "hi", "keyboardTypeDelay": 10, "inputStrategy": "bulk"},
            device,
            None,
        )
        assert device.typed == "hi"


class TestPlatformFixes:
    @pytest.mark.asyncio
    async def test_selenium_scroll_passes_numbers_as_arguments(self):
        pytest.importorskip("selenium")
        from midscene.web.selenium_page import SeleniumWebPage

        class Driver:
            def __init__(self):
                self.calls = []

            def execute_script(self, script, *args):
                self.calls.append((script, args))
                return None

        page = SeleniumWebPage.__new__(SeleniumWebPage)
        page.driver = Driver()

        await page.scroll("down", distance="120")
        assert page.driver.calls[-1] == (
            "window.scrollBy(arguments[0], arguments[1]);",
            (0, 120),
        )

        with pytest.raises(ValueError):
            await page.scroll("down", distance="0);alert(1)//")
        assert len(page.driver.calls) == 1

    @pytest.mark.asyncio
    async def test_playwright_scroll_defaults_to_viewport_and_centers_mouse(self):
        from midscene.web.playwright_page import PlaywrightWebPage

        class Mouse:
            def __init__(self):
                self.calls = []

            async def move(self, x, y):
                self.calls.append(("move", x, y))

            async def wheel(self, x, y):
                self.calls.append(("wheel", x, y))

        class Page:
            def __init__(self):
                self.mouse = Mouse()
                self.viewport_size = {"width": 1000, "height": 800}

        page = PlaywrightWebPage.__new__(PlaywrightWebPage)
        page.page = Page()
        with patch("midscene.web.playwright_page.asyncio.sleep", AsyncMock()):
            await page.scroll("down")
            await page.scroll("right")
        assert page.page.mouse.calls == [
            ("move", 500, 400),
            ("wheel", 0, 560.0),
            ("move", 500, 400),
            ("wheel", 700.0, 0),
        ]

    @pytest.mark.asyncio
    async def test_bridge_scroll_defaults_to_viewport_and_centers_mouse(self):
        from midscene.web.bridge import BridgeWebPage

        class Server:
            def __init__(self):
                self.calls = []

            async def call(self, name, args):
                self.calls.append((name, args))
                if name == "size":
                    return {"width": 1000, "height": 800}
                return None

        page = BridgeWebPage()
        page._server = Server()
        page._connected = True
        await page.scroll("up")
        assert page._server.calls == [
            ("size", []),
            ("mouse.move", [500, 400]),
            ("mouse.wheel", [0, -560.0]),
        ]

    @pytest.mark.asyncio
    async def test_selenium_scroll_defaults_to_viewport(self):
        pytest.importorskip("selenium")
        from midscene.web.selenium_page import SeleniumWebPage

        class Driver:
            def __init__(self):
                self.calls = []

            def get_window_size(self):
                return {"width": 1000, "height": 800}

            def execute_script(self, script, *args):
                self.calls.append((script, args))

        page = SeleniumWebPage.__new__(SeleniumWebPage)
        page.driver = Driver()
        await page.scroll("left")
        assert page.driver.calls[-1] == (
            "window.scrollBy(arguments[0], arguments[1]);",
            (-700.0, 0),
        )

    @pytest.mark.asyncio
    async def test_android_keyboard_press_arrow_keys(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = False
        sent = []

        async def key_event(key_code):
            sent.append(key_code)

        device.key_event = key_event
        await device.keyboard_press("ArrowUp")
        await device.keyboard_press("Control+A")
        assert sent == ["KEYCODE_DPAD_UP", "KEYCODE_A"]

    @pytest.mark.asyncio
    async def test_drag_and_drop_resolves_both_points(self):
        from midscene.core.actions import _execute_drag_and_drop

        class DragDevice:
            def __init__(self):
                self.calls = []

            async def drag_and_drop(self, from_point, to_point):
                self.calls.append((tuple(from_point), tuple(to_point)))

        async def locate_fn(locate_param):
            x = 300 if "zone" in locate_param["prompt"] else 100
            return {"center": (x, 50), "rect": None, "description": "x"}

        device = DragDevice()
        await _execute_drag_and_drop(
            {"from": {"prompt": "the card"}, "to": {"prompt": "the drop zone"}},
            device,
            locate_fn,
        )
        assert device.calls == [((100, 50), (300, 50))]

    @pytest.mark.asyncio
    async def test_drag_and_drop_requires_primitive(self):
        from midscene.core.actions import _execute_drag_and_drop

        class NoDrag:
            pass

        with pytest.raises(NotImplementedError):
            await _execute_drag_and_drop(
                {"from": {"prompt": "a"}, "to": {"prompt": "b"}}, NoDrag(), None
            )

    @pytest.mark.asyncio
    async def test_yaml_ai_drag_and_drop(self):
        from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

        script = parse_yaml_script(
            """
tasks:
  - name: drag
    flow:
      - aiDragAndDrop:
          from:
            prompt: the card
          to:
            prompt: the drop zone
"""
        )

        class DragInterface(MockInterface):
            def __init__(self):
                super().__init__()
                self.dragged = []

            async def drag_and_drop(self, from_point, to_point):
                self.dragged.append((tuple(from_point), tuple(to_point)))

        interface = DragInterface()

        async def fake_locate(locate_param):
            x = 300 if "zone" in locate_param["prompt"] else 100
            return {"center": (x, 50), "rect": None, "description": "x"}

        agent = _make_agent(interface)
        with patch.object(agent, "_locate_for_action", fake_locate):
            await ScriptPlayer(script, agent).run()
        assert interface.dragged == [((100, 50), (300, 50))]

    @pytest.mark.asyncio
    async def test_android_drag_and_drop_uses_swipe(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice.__new__(AndroidDevice)
        device._connected = False
        calls = []

        async def swipe(start_x, start_y, end_x, end_y, duration=300, distance=None):
            calls.append((start_x, start_y, end_x, end_y, duration))

        device.swipe = swipe
        await device.drag_and_drop((10, 20), (30, 40))
        assert calls == [(10, 20, 30, 40, 1000)]

    @pytest.mark.asyncio
    async def test_selenium_drag_and_drop_uses_relative_offsets(self):
        from midscene.web.selenium_page import SeleniumWebPage

        class FakeChains:
            def __init__(self):
                self.calls = []

            def move_by_offset(self, x, y):
                self.calls.append(("move_by_offset", x, y))
                return self

            def click_and_hold(self):
                self.calls.append(("click_and_hold",))
                return self

            def release(self):
                self.calls.append(("release",))
                return self

            def perform(self):
                self.calls.append(("perform",))
                return self

            def reset_actions(self):
                self.calls.append(("reset_actions",))

        page = SeleniumWebPage.__new__(SeleniumWebPage)
        page._action_chains = FakeChains()

        await page.drag_and_drop((100, 200), (300, 400))

        assert page._action_chains.calls == [
            ("move_by_offset", 100, 200),
            ("click_and_hold",),
            ("move_by_offset", 200, 200),
            ("release",),
            ("perform",),
            ("reset_actions",),
        ]

    @pytest.mark.asyncio
    async def test_bridge_call_response_round_trip(self):
        """Extension client receives bridge-call and its response resolves
        the server-side call (Socket.IO protocol)."""
        import socketio

        from midscene.web.bridge import BridgeServer

        # listen() on an ephemeral port: exercises the real server config
        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]

        received: list = []

        client = socketio.AsyncClient()

        @client.on("bridge-call")
        async def on_call(data):
            received.append(data)
            await client.emit(
                "bridge-call-response",
                {"id": data["id"], "response": {"clicked": True}},
            )

        import aiohttp

        session = aiohttp.ClientSession(
            headers={"Origin": "chrome-extension://testext"}
        )
        client.eio.http = session
        try:
            await client.connect(
                f"ws://127.0.0.1:{port}",
                transports=["websocket"],
                socketio_path="socket.io",
            )
            for _ in range(100):
                if server._client_sid is not None:
                    break
                await asyncio.sleep(0.02)
            assert server._client_sid is not None

            response = await server.call("mouse.click", [10, 20], timeout=5)
            assert response == {"clicked": True}
            assert received[0]["method"] == "mouse.click"
            assert received[0]["args"] == [10, 20]
        finally:
            await client.disconnect()
            await session.close()
            await server.close()

    @pytest.mark.asyncio
    async def test_bridge_rejects_untrusted_origin(self):
        import socketio

        from midscene.web.bridge import BridgeServer

        server = BridgeServer()
        sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
        sio.on("connect", server._on_connect)
        sio.on("disconnect", server._on_disconnect)
        sio.on("bridge-call-response", server._on_call_response)

        environ = {"HTTP_ORIGIN": "https://evil.com"}
        result = await server._on_connect("sid1", environ)
        assert result is False  # connection rejected

        # trusted origin connects and sets the client sid
        await server._on_connect(
            "sid2", {"HTTP_ORIGIN": "chrome-extension://testext", "QUERY_STRING": ""}
        )
        assert server._client_sid == "sid2"

    @pytest.mark.asyncio
    async def test_bridge_listen_timeout_without_client(self):
        from midscene.web.bridge import BridgeServer

        server = BridgeServer(port=0)
        with pytest.raises(RuntimeError) as exc:
            await server.listen(timeout=0.3)
        assert "no extension connected" in str(exc.value)

    def test_action_space_ignores_unimplemented_stubs(self):
        from midscene.core.types import AbstractInterface, InterfaceType

        class StubInterface(AbstractInterface):
            @property
            def interface_type(self):
                return InterfaceType.WEB

            async def get_context(self):
                return None

            async def action_space(self):
                return []

            async def tap(self, x, y):
                pass

            async def input_text(self, text):
                pass

            async def scroll(self, direction, distance=None, **kwargs):
                pass

        names = {action.name for action in _make_agent(StubInterface()).action_space}
        assert {"Tap", "Input", "Scroll"} <= names
        assert "DragAndDrop" not in names
        assert "RightClick" not in names


class TestBridgeProtocol:
    """Regression tests for the Chrome-extension bridge wire protocol."""

    class RecordingServer:
        def __init__(self):
            self.calls: List[tuple] = []

        async def call(self, method, args=None, timeout=None):
            self.calls.append((method, args))
            if method == "size":
                return {"width": 100, "height": 50}
            if method == "screenshotBase64":
                return "data:image/jpeg;base64,AAAA"
            return None

    def _connected_page(self):
        from midscene.web.bridge import BridgeWebPage

        page = BridgeWebPage()
        recorder = self.RecordingServer()
        page._server = recorder
        page._connected = True
        return page, recorder

    def test_build_key_commands_matches_extension_shape(self):
        from midscene.web.bridge import build_key_commands

        assert build_key_commands("Enter") == [{"key": "Enter"}]
        assert build_key_commands("Control+A") == [
            {"key": "Control"},
            {"key": "A", "command": "SelectAll"},
        ]
        assert build_key_commands("Command+C") == [
            {"key": "Meta"},
            {"key": "C", "command": "Copy"},
        ]
        assert build_key_commands("page down") == [{"key": "PageDown"}]
        assert build_key_commands("+") == [{"key": "+"}]

    @pytest.mark.asyncio
    async def test_keyboard_press_sends_key_objects(self):
        # the extension dispatches CDP Input.dispatchKeyEvent from {key, command}
        page, recorder = self._connected_page()
        await page.keyboard_press("Enter")
        assert recorder.calls[-1] == ("keyboard.press", [[{"key": "Enter"}]])
        await page.keyboard_press("Control+A")
        assert recorder.calls[-1] == (
            "keyboard.press",
            [[{"key": "Control"}, {"key": "A", "command": "SelectAll"}]],
        )

    @pytest.mark.asyncio
    async def test_mouse_primitives_map_to_extension_arguments(self):
        page, recorder = self._connected_page()
        await page.right_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"button": "right"}])
        await page.middle_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"button": "middle"}])
        await page.double_click(10, 20)
        assert recorder.calls[-1] == ("mouse.click", [10, 20, {"count": 2}])
        await page.drag_and_drop((1, 2), (3, 4))
        assert recorder.calls[-1] == (
            "mouse.drag", [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
        )
        await page.long_press(5, 6)
        assert recorder.calls[-1] == ("longPress", [5, 6, 1000])

    @pytest.mark.asyncio
    async def test_pinch_maps_to_extension_arguments(self):
        """Upstream labels: 'in' pinches the fingers together, 'out' spreads
        them apart."""
        page, recorder = self._connected_page()
        await page.pinch("in", point=[10, 20], distance=120)
        assert recorder.calls[-1] == ("pinch", [10, 20, 120.0, 20.0, 500])
        await page.pinch("out", point=[10, 20], distance=120)
        assert recorder.calls[-1] == ("pinch", [10, 20, 20.0, 120.0, 500])
        with pytest.raises(ValueError):
            await page.pinch("sideways")

    def test_bridge_action_space_matches_extension_primitives(self):
        from midscene.web.bridge import BridgeWebPage

        names = {action.name for action in _make_agent(BridgeWebPage()).action_space}
        assert {
            "Tap", "RightClick", "MiddleClick", "DoubleClick", "Hover",
            "DragAndDrop", "KeyboardPress", "Scroll", "Input", "Pinch",
            "ClearInput", "CursorMove", "Navigate", "Reload", "GoBack",
            "GoForward",
        } <= names

    @pytest.mark.asyncio
    async def test_get_context_describes_the_viewport_root(self):
        page, _ = self._connected_page()
        context = await page.get_context()
        assert (context.size.width, context.size.height) == (100, 50)
        assert context.tree.node.rect.width == 100
        assert context.tree.node.center == (50, 25)

    @pytest.mark.asyncio
    async def test_page_methods_require_connect(self):
        from midscene.web.bridge import BridgeWebPage

        page = BridgeWebPage()
        with pytest.raises(RuntimeError, match="not connected"):
            await page.tap(1, 2)

    @pytest.mark.asyncio
    async def test_close_flushes_pending_calls(self):
        from types import SimpleNamespace

        from midscene.web.bridge import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        server._client_sid = "sid"
        server._sio = SimpleNamespace(emit=AsyncMock())
        task = asyncio.create_task(server.call("mouse.click", [1, 2], timeout=30))
        await asyncio.sleep(0.05)
        await server.close()
        with pytest.raises(RuntimeError, match="Bridge server closed"):
            await task

    @pytest.mark.asyncio
    async def test_disconnect_flushes_pending_calls(self):
        from midscene.web.bridge import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        server._client_sid = "sid"
        loop = asyncio.get_running_loop()
        pending = loop.create_future()
        server._pending["1"] = pending
        await server._on_disconnect("sid")
        with pytest.raises(RuntimeError, match="Connection lost"):
            await pending

    @pytest.mark.asyncio
    async def test_listen_kills_conflicting_server_on_the_real_port(self):
        import socket as _socket

        from midscene.web import bridge as bridge_module

        probe = _socket.socket()
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()

        seen: List[tuple] = []

        async def fake_kill(port, host):
            seen.append((port, host))

        with patch.object(bridge_module, "kill_running_server", fake_kill):
            server = bridge_module.BridgeServer(host="127.0.0.1", port=free_port)
            await server.listen(timeout=False)
            try:
                assert seen == [(free_port, "127.0.0.1")]
            finally:
                await server.close()

            ephemeral = bridge_module.BridgeServer(host="127.0.0.1", port=0)
            await ephemeral.listen(timeout=False)
            try:
                assert seen == [(free_port, "127.0.0.1")]  # no kill for port 0
            finally:
                await ephemeral.close()

    @pytest.mark.asyncio
    async def test_polling_handshake_echoes_extension_origin(self):
        """CORS must stay open at the HTTP layer or the extension's first
        XHR poll (chrome-extension:// origin) is blocked by the browser."""
        import aiohttp

        from midscene.web.bridge import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]
        try:
            async with aiohttp.ClientSession(
                headers={"Origin": "chrome-extension://testext"}
            ) as session:
                async with session.get(
                    f"http://127.0.0.1:{port}/socket.io/?EIO=4&transport=polling"
                ) as response:
                    assert response.status == 200
                    assert (
                        response.headers.get("Access-Control-Allow-Origin")
                        == "chrome-extension://testext"
                    )
        finally:
            await server.close()

    @pytest.mark.asyncio
    async def test_second_client_receives_bridge_refused(self):
        import socketio

        from midscene.web.bridge import BridgeServer

        server = BridgeServer(host="127.0.0.1", port=0, close_conflict_server=False)
        await server.listen(timeout=False)
        port = server._runner.addresses[0][1]

        sessions = []

        def make_client():
            import aiohttp

            client = socketio.AsyncClient()
            session = aiohttp.ClientSession(
                headers={"Origin": "chrome-extension://testext"}
            )
            sessions.append(session)
            client.eio.http = session
            return client

        refused = asyncio.Event()

        first = make_client()
        second = make_client()

        @second.on("bridge-refused")
        async def _on_refused(*args):
            refused.set()
        try:
            await first.connect(
                f"ws://127.0.0.1:{port}", transports=["websocket"],
                socketio_path="socket.io",
            )
            for _ in range(100):
                if server._client_sid is not None:
                    break
                await asyncio.sleep(0.02)
            assert server._client_sid is not None

            await second.connect(
                f"ws://127.0.0.1:{port}", transports=["websocket"],
                socketio_path="socket.io",
            )
            try:
                await asyncio.wait_for(refused.wait(), timeout=3)
            except asyncio.TimeoutError:
                pytest.fail("the second client never received bridge-refused")
        finally:
            for client in (first, second):
                try:
                    await client.disconnect()
                except Exception:
                    pass
            for session in sessions:
                await session.close()
            await server.close()


class TestYamlExtras:
    @pytest.mark.asyncio
    async def test_javascript_and_json_output(self, tmp_path):
        from midscene.core.yaml_runner import ScriptPlayer, parse_yaml_script

        output = tmp_path / "result.json"
        script = parse_yaml_script(
            "config:\n"
            f"  output: {output}\n"
            "tasks:\n"
            "  - name: t\n"
            "    flow:\n"
            "      - javascript:\n"
            "          script: document.title\n"
            "        name: title\n"
        )

        interface = MockInterface()

        async def evaluate_script(script_text):
            return "示例标题"

        interface.evaluate_script = evaluate_script

        player = ScriptPlayer(script, _make_agent(interface))
        await player.run()

        assert player.status == "done"
        assert json.loads(output.read_text(encoding="utf-8")) == {"title": "示例标题"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestDeepLocatePlanHint:
    """deepLocate must not let plan coordinates shortcut the two-stage locate
    (upstream task-builder: elementFromPlan = deepLocate ? undefined : ...)."""

    @pytest.mark.asyncio
    async def test_plan_coords_become_search_hint(self, mock_interface):
        from midscene.core.agent import Agent
        from midscene.core.types import AgentOptions

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
            "midscene.core.agent.locate_service", new=fake_locate_service
        ):
            element = await agent._locate_for_action(locate_param)

        # The plan coordinates were NOT returned directly; they were forwarded
        # as the search-area hint for the two-stage locate.
        assert element["center"] == (123, 45)
        assert captured["deep_locate"] is True
        assert captured["plan_located_element"] == {"center": (160, 120)}

    @pytest.mark.asyncio
    async def test_plan_coords_direct_hit_without_deep_locate(self, mock_interface):
        from midscene.core.agent import Agent
        from midscene.core.types import AgentOptions

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
        with patch("midscene.core.agent.locate_service", new=fail_if_called):
            element = await agent._locate_for_action(locate_param)
        assert element["center"] == (160, 120)
