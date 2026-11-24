"""System One entry point and OpenAI dispatch helpers."""

from typing import Any
from unittest.mock import patch

import pytest


def _jev_runtime(**overrides):
    from midscene.core.ai_model.models.registry import get_model_runtime

    config = {
        "modelName": "jev-1",
        "modelFamily": "jev",
        "intent": "default",
        "slot": "default",
        "retryCount": 0,
        "retryInterval": 0,
    }
    config.update(overrides)
    return get_model_runtime(config)


def _runtime(**overrides):
    from midscene.core.ai_model.models.registry import get_model_runtime

    config = {
        "modelName": "mock-model",
        "intent": "default",
        "slot": "default",
        "retryCount": 0,
        "retryInterval": 0,
        "responseFormat": "none",
    }
    config.update(overrides)
    return get_model_runtime(config)


class TestCallSystemOneAI:
    @pytest.mark.asyncio
    async def test_rejects_streaming_before_entering_the_retry_loop(self):
        from midscene.core.ai_model.service_caller.call_ai import call_system_one_ai

        with patch(
            "midscene.core.ai_model.service_caller.call_ai.call_system_one"
        ) as call_system_one:
            with pytest.raises(
                RuntimeError, match="^Jev does not support streaming output$"
            ):
                await call_system_one_ai(
                    {"state": {}, "questions": {}},
                    _jev_runtime(),
                    {"stream": True, "onChunk": lambda chunk: None},
                )
        call_system_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_the_jev_model_family(self):
        from midscene.core.ai_model.service_caller.call_ai import call_system_one_ai

        with pytest.raises(
            RuntimeError,
            match="System One currently only supports the Jev model family",
        ):
            await call_system_one_ai({"state": {}, "questions": {}}, _runtime())

    @pytest.mark.asyncio
    async def test_retries_malformed_responses_without_changing_the_model(self):
        from midscene.core.ai_model.service_caller.call_ai import call_system_one_ai
        from midscene.core.ai_model.service_caller.types import AIResponseParseError

        calls: list[dict[str, Any]] = []

        async def fake_call_system_one(model_runtime, request):
            calls.append(request)
            if len(calls) == 1:
                raise AIResponseParseError("Invalid System One response", "bad")
            return {
                "content": "ok",
                "answers": {"target": {"type": "noul", "noul": 1}},
                "usage": None,
                "response_model_name": "jev-1",
            }

        with patch(
            "midscene.core.ai_model.service_caller.call_ai.call_system_one",
            new=fake_call_system_one,
        ):
            result = await call_system_one_ai(
                {"state": {}, "questions": {}},
                _jev_runtime(retryCount=1, retryInterval=0),
            )

        assert result["content"] == "ok"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_preserves_parse_error_type_after_all_attempts_fail(self):
        from midscene.core.ai_model.service_caller.call_ai import call_system_one_ai
        from midscene.core.ai_model.service_caller.types import AIResponseParseError

        async def fake_call_system_one(model_runtime, request):
            raise AIResponseParseError("Invalid System One response", "bad")

        with patch(
            "midscene.core.ai_model.service_caller.call_ai.call_system_one",
            new=fake_call_system_one,
        ):
            with pytest.raises(AIResponseParseError) as exc_info:
                await call_system_one_ai(
                    {"state": {}, "questions": {}},
                    _jev_runtime(retryCount=1, retryInterval=0),
                )

        assert exc_info.value.raw_response == "bad"
        assert "2/2 attempts" in str(exc_info.value)
        assert "Invalid System One response" in str(exc_info.value)


class TestOpenAIDispatch:
    @pytest.mark.asyncio
    async def test_call_open_ai_dispatches_responses_and_forwards_context(
        self, monkeypatch
    ):
        import importlib

        from midscene.core.ai_model.service_caller.openai import call_openai

        module = importlib.import_module(
            "midscene.core.ai_model.service_caller.openai.call_openai"
        )
        assert module is not call_openai
        captured: dict[str, Any] = {}
        runtime = _runtime()

        async def fake_call_openai(*args, **kwargs):
            captured.update({"args": args, "kwargs": kwargs})
            return {"content": "ok"}

        monkeypatch.setattr(module, "call_openai", fake_call_openai)

        result = await module.call_open_ai(
            {
                "modelRuntime": runtime,
                "options": {"stream": False},
                "executionId": "exec-1",
                "effectiveTimeoutMs": 1000,
            },
            {"kind": "responses", "input": {"requestParams": {"model": "m"}}},
        )

        assert result == {"content": "ok"}
        assert captured["args"][1] == "openai-responses"
        assert captured["args"][2]["request_body"] == {"model": "m"}
        assert captured["kwargs"]["execution_id"] == "exec-1"
        assert captured["kwargs"]["effective_timeout"] == 1000

    @pytest.mark.asyncio
    async def test_call_chat_completion_selects_stream_or_payload(self, monkeypatch):
        from midscene.core.ai_model.service_caller.openai.chat_completion import (
            chat_completion,
        )

        non_stream_calls: list[Any] = []
        stream_calls: list[Any] = []

        def fake_non_stream(payload, adapter):
            non_stream_calls.append((payload, adapter))
            return {"content": "non-stream"}

        async def fake_stream(lines, adapter, on_chunk=None):
            stream_calls.append((lines, adapter, on_chunk))
            return {"content": "stream"}

        monkeypatch.setattr(
            chat_completion, "call_chat_completion_non_streaming", fake_non_stream
        )
        monkeypatch.setattr(chat_completion, "call_chat_completion_stream", fake_stream)

        payload = {"choices": []}
        lines = object()
        assert (
            await chat_completion.call_chat_completion(
                {"payload": payload, "adapter": "adapter"}, False
            )
        ) == {"content": "non-stream"}
        assert (
            await chat_completion.call_chat_completion(
                {"lines": lines, "adapter": "adapter"}, True
            )
        ) == {"content": "stream"}
        assert non_stream_calls == [(payload, "adapter")]
        assert stream_calls[0][0] is lines

    @pytest.mark.asyncio
    async def test_call_responses_selects_stream_or_payload(self, monkeypatch):
        from midscene.core.ai_model.service_caller.openai.responses import responses

        non_stream_calls: list[Any] = []
        stream_calls: list[Any] = []
        monkeypatch.setattr(
            responses,
            "call_responses_non_streaming",
            lambda payload: non_stream_calls.append(payload) or {"content": "ns"},
        )

        async def fake_stream(lines, on_chunk=None):
            stream_calls.append((lines, on_chunk))
            return {"content": "s"}

        monkeypatch.setattr(responses, "call_responses_stream", fake_stream)

        payload = {"output": []}
        lines = object()
        assert await responses.call_responses({"payload": payload}, False) == {
            "content": "ns"
        }
        assert await responses.call_responses({"lines": lines}, True) == {
            "content": "s"
        }
        assert non_stream_calls == [payload]
        assert stream_calls[0][0] is lines
