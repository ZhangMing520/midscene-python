"""
Tests for the second wave of upstream alignment (v1.17.4):
System One / Jev, custom planners (UI-TARS / Auto-GLM), DeepLocate,
YAML runner, dump structure, connectivity, model fallback.
"""

import asyncio
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

        async def fake_call_system_one(runtime, request):
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "present": {"type": "noul", "noul": 0.95},
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

    @pytest.mark.asyncio
    async def test_jev_locate_not_present(self):
        from midscene.core.ai_model.workflows.jev import jev_locate

        async def fake_call_system_one(runtime, request):
            return {
                "content": "raw",
                "usage": None,
                "answers": {
                    "present": {"type": "noul", "noul": 0.2},
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
                "missing", {"imageBase64": make_png_base64(), "width": 320, "height": 240}, None
            )
        assert "errors" in result
        assert "locatedPixelResult" not in result

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
                    "retryCount": 0,
                    "retryInterval": 0,
                }
            )
            result = await caller.call_generative_ai(
                [{"role": "user", "content": "hi"}], runtime, {}
            )

        assert result["content"] == "ok"
        refresh.assert_awaited_once_with("old-token")

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
    async def test_bridge_handler_accepts_asyncio_websockets_api(self):
        import websockets

        from midscene.web.bridge import BridgeWebPage

        bridge = BridgeWebPage("ws://localhost:0")
        server = await websockets.serve(bridge._handle_connection, "localhost", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            async with websockets.connect(f"ws://localhost:{port}") as client:
                await client.send('{"hello": 1}')
                for _ in range(100):
                    if bridge.websocket is not None:
                        break
                    await asyncio.sleep(0.01)
                assert bridge.websocket is not None
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_bridge_connect_uses_url_host_and_port(self, monkeypatch):
        import websockets

        from midscene.web.bridge import BridgeWebPage

        captured = {}

        async def fake_serve(handler, host, port):
            captured.update(host=host, port=port)

            class FakeServer:
                def close(self):
                    pass

                async def wait_closed(self):
                    pass

            return FakeServer()

        monkeypatch.setattr(websockets, "serve", fake_serve)
        bridge = BridgeWebPage("ws://127.0.0.1:9000")
        bridge.websocket = object()
        await bridge.connect()

        assert captured == {"host": "127.0.0.1", "port": 9000}

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
