"""Synced from upstream packages/core/tests/unit-test/jev.test.ts."""

import base64
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tests.core_helpers import FakeResponse, make_png_base64


class TestSystemOne:
    def _response(self, answers: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "model": "jev-1",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    def test_validate_response_accepts_valid(self):
        from midscene.core.ai_model.service_caller.system_one import validate_system_one_response

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
        from midscene.core.ai_model.service_caller.system_one import SystemOneError, validate_system_one_response

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
        from midscene.core.ai_model.service_caller.system_one import SystemOneError, validate_system_one_response

        payload = self._response({"present": {"type": "noul", "noul": 1.5}})
        with pytest.raises(SystemOneError):
            validate_system_one_response(payload)

    def test_encode_images_openrouter_inline(self):
        from midscene.core.ai_model.service_caller.system_one import encode_system_one_images

        data_url = "data:image/png;base64,AAAA"
        state, assets = encode_system_one_images({"shot": data_url}, True)
        assert state["shot"]["type"] == "image_url"
        assert assets == {}

    def test_encode_images_assets(self):
        from midscene.core.ai_model.service_caller.system_one import encode_system_one_images

        data_url = "data:image/jpeg;base64,BBBB"
        state, assets = encode_system_one_images({"shot": data_url}, False)
        assert state["shot"]  # reference id
        assert list(assets.values())[0]["format"] == "jpg"

    def test_resolve_endpoint(self):
        from midscene.core.ai_model.service_caller.system_one import resolve_system_one_endpoint

        assert (
            resolve_system_one_endpoint({"openaiBaseURL": "https://x/v1/"})
            == "https://x/v1/systemone"
        )
        assert resolve_system_one_endpoint({"endpoint": "https://y"}) == "https://y"

    def test_prepare_includes_execution_id_header(self):
        from midscene.core.ai_model.service_caller.system_one import prepare_system_one

        config = {
            "openaiApiKey": "sk-test",
            "openaiBaseURL": "https://api.example.com/v1",
            "modelName": "jev-1",
        }
        request = {"state": {}, "questions": {}}
        prepared = prepare_system_one(config, request, execution_id="exec-123")
        assert prepared["headers"]["x-midscene-execution-id"] == "exec-123"
        assert prepare_system_one(config, request)["headers"].get(
            "x-midscene-execution-id"
        ) is None

    @pytest.mark.asyncio
    async def test_call_sends_stable_runtime_execution_id(self):
        from midscene.core.ai_model.service_caller import system_one

        captured: List[Dict[str, str]] = []
        payload = self._response({"present": {"type": "noul", "noul": 0.9}})

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, content=None):
                captured.append(headers)
                return FakeResponse(payload)

        runtime = _make_runtime(
            modelFamily="jev",
            openaiApiKey="sk-test",
            openaiBaseURL="https://api.example.com/v1",
        )
        request = {
            "state": {"present": "`screenshot`"},
            "questions": {"present": {"type": "noul"}},
        }
        with patch.object(system_one.httpx, "AsyncClient", FakeAsyncClient):
            await system_one.call_system_one(runtime, request)
            await system_one.call_system_one(runtime, request)

        execution_id = captured[0]["x-midscene-execution-id"]
        assert execution_id.startswith("unscoped-")
        assert captured[1]["x-midscene-execution-id"] == execution_id

    @pytest.mark.asyncio
    async def test_call_wraps_invalid_response_in_parse_error(self):
        from midscene.core.ai_model.service_caller import system_one
        from midscene.core.ai_model.service_caller.types import AIResponseParseError

        payload = {"answers": {"present": {"type": "noul", "noul": 1.5}}}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, headers=None, content=None):
                return FakeResponse(payload)

        runtime = _make_runtime(
            modelFamily="jev",
            openaiApiKey="sk-test",
            openaiBaseURL="https://api.example.com/v1",
        )
        with patch.object(system_one.httpx, "AsyncClient", FakeAsyncClient):
            with pytest.raises(AIResponseParseError) as exc:
                await system_one.call_system_one(
                    runtime,
                    {"state": {}, "questions": {"present": {"type": "noul"}}},
                )

        # The raw body must survive for the caller's semantic retry.
        assert '"noul": 1.5' in exc.value.raw_response



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


class TestJevWorkflows:
    @pytest.mark.asyncio
    async def test_jev_locate(self):
        from midscene.core.ai_model.models.jev.locate import jev_locate

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
            "midscene.core.ai_model.models.jev.locate.call_system_one",
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
        from midscene.core.ai_model.models.jev.locate import jev_locate

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
            "midscene.core.ai_model.models.jev.locate.call_system_one",
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
        from midscene.core.ai_model.models.jev.locate import jev_locate

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
            "midscene.core.ai_model.models.jev.locate.call_system_one",
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
        from midscene.core.ai_model.models.jev.locate import jev_locate

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
            "midscene.core.ai_model.models.jev.locate.call_system_one",
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
        from midscene.core.ai_model.models.jev.locate import jev_locate

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
            "midscene.core.ai_model.models.jev.locate.call_system_one",
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
        from midscene.core.ai_model.models.jev.boolean import jev_boolean

        async def fake_call_system_one(runtime, request):
            return {
                "content": "raw",
                "usage": {"total_tokens": 4},
                "answers": {"result": {"type": "noul", "noul": 0.8}},
            }

        with patch(
            "midscene.core.ai_model.models.jev.boolean.call_system_one",
            new=fake_call_system_one,
        ):
            class _Ctx:
                screenshot_base64 = make_png_base64()

            result = await jev_boolean("the page is loaded", _Ctx(), None)
        assert result["value"] is True

    def test_build_jev_action_attaches_reference_images(self):
        from midscene.core.device import build_web_action_space
        from midscene.core.ai_model.models.jev.planning_action import build_jev_action

        tap = next(a for a in build_web_action_space() if a.name == "Tap")
        actions = build_jev_action(
            {"choice": {"kind": "action", "action": tap}, "target": None},
            {"state": {"goal": "open the menu"}},
            "open the menu",
            [tap],
            False,
            {"width": 320, "height": 240},
            reference_images=["data:image/png;base64,AAAA"],
        )
        assert actions[0]["type"] == "Tap"
        locate = actions[0]["param"]["locate"]
        assert 'Locate the target for parameter "locate"' in locate["prompt"]["prompt"]
        assert locate["prompt"]["images"] == [{"url": "data:image/png;base64,AAAA"}]

    def test_build_jev_action_complete_yields_no_actions(self):
        from midscene.core.ai_model.models.jev.planning_action import build_jev_action

        assert (
            build_jev_action(
                {"choice": {"kind": "complete"}},
                {"state": {}},
                "done",
                [],
                False,
                {"width": 320, "height": 240},
            )
            == []
        )



class TestModelFallback:
    def test_jev_extracts_fall_back_to_default(self):
        from midscene.core.ai_model.models import resolve_model_for_task_type

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



class TestPrepareReferences:
    @pytest.mark.asyncio
    async def test_collects_reference_images(self):
        from midscene.core.ai_model.models.jev.image import prepare_references

        data_uri = "data:image/png;base64," + make_png_base64(2, 2)
        result = await prepare_references(
            {"images": [{"url": data_uri, "name": "reference"}]}
        )
        assert len(result["images"]) == 1
        assert result["references"] == [
            {"image": "`reference_0`", "name": "reference"}
        ]
