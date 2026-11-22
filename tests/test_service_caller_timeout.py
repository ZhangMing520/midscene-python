"""Synced from upstream packages/core/tests/unit-test/service-caller-timeout.test.ts."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from tests.core_helpers import FakeResponse


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


class TestServiceCallerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_passed_to_httpx_in_seconds(self):
        from midscene.core.ai_model.service_caller import model_call

        captured: List[Dict[str, Any]] = []

        class RecordingClient(_StubAsyncClient):
            def __init__(self, *args, **kwargs):
                captured.append(kwargs)
                super().__init__([FakeResponse(_chat_completion_payload())])

        with patch.object(
            model_call.httpx,
            "AsyncClient",
            lambda *a, **k: RecordingClient(*a, **k),
        ):
            await model_call._post_json(
                url="https://example.com/v1/chat/completions",
                headers={},
                request_body={"model": "m", "messages": []},
                effective_timeout=5000,
                proxy=None,
                stream=False,
            )

        assert captured[0]["timeout"].read == 5.0

    def test_default_timeout_is_180s(self):
        from midscene.core.ai_model.service_caller.request_timeout import resolve_effective_timeout_ms

        assert resolve_effective_timeout_ms(None) == 180_000.0
        assert resolve_effective_timeout_ms(0) is None
        assert resolve_effective_timeout_ms(2500) == 2500.0

