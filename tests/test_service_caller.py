"""Synced from upstream packages/core/tests/unit-test/service-caller-*,
semantic-retry.test.ts and service-caller-timeout.test.ts."""

import json
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest


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


class FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"x-request-id": "req-1"}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _chat_payload(
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


async def _run_call(responses, model_config_overrides=None, **call_options):
    from midscene.core.ai_model.service_caller import call_ai as caller
    from midscene.core.ai_model.service_caller import model_call

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

    with patch.object(model_call.httpx, "AsyncClient", FakeAsyncClient):
        runtime = make_runtime(**(model_config_overrides or {}))
        return await caller.call_generative_ai(
            [{"role": "user", "content": "hi"}], runtime, call_options
        )


@pytest.mark.asyncio
async def test_sends_text_messages_and_reports_normalized_usage():
    result = await _run_call([FakeResponse(_chat_payload("hello world"))])

    assert result["content"] == "hello world"
    assert result["usage"]["total_tokens"] == 150
    assert result["usage"]["prompt_tokens"] == 100


@pytest.mark.asyncio
async def test_increments_the_semantic_retry_attempt_after_parsing_failures():
    result = await _run_call(
        [FakeResponse(_chat_payload("ok"))], semanticRetryAttempt=2
    )

    usage = result["usage"]
    assert usage["request_retry_count"] == 0
    assert usage["parse_retry_count"] == 2
    # `retry` predates the upstream split; keep it as the sum.
    assert usage["retry"] == 2


@pytest.mark.asyncio
async def test_uses_reasoning_content_when_content_is_empty():
    result = await _run_call(
        [FakeResponse(_chat_payload("", reasoning="thinking output"))]
    )

    assert result["content"] == "thinking output"


@pytest.mark.asyncio
async def test_throws_when_content_is_empty_and_reasoning_fallback_is_not_enabled():
    from midscene.core.ai_model.service_caller.types import AIResponseParseError

    with pytest.raises(AIResponseParseError):
        await _run_call([FakeResponse(_chat_payload("", reasoning=None))])


@pytest.mark.asyncio
async def test_retries_after_a_hard_timeout_and_returns_the_next_successful_response():
    result = await _run_call(
        [
            FakeResponse({"error": "boom"}, status_code=500),
            FakeResponse(_chat_payload("recovered")),
        ],
        model_config_overrides={"retryCount": 1, "retryInterval": 0},
    )

    assert result["content"] == "recovered"


@pytest.mark.asyncio
async def test_includes_previous_attempt_errors_when_all_retry_attempts_fail():
    with pytest.raises(RuntimeError) as exc:
        await _run_call(
            [
                FakeResponse({"error": "boom"}, status_code=500),
                FakeResponse({"error": "boom"}, status_code=500),
            ],
            model_config_overrides={"retryCount": 1, "retryInterval": 0},
        )

    assert "1 retry" in str(exc.value) or "retries" in str(exc.value)
