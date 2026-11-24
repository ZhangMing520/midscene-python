"""Synced from upstream packages/core/tests/unit-test/service-caller-siwc.test.ts."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.core_helpers import FakeResponse


def _chat_completion_payload(content: str = "ok") -> dict[str, Any]:
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


class TestServiceCallerSiwc:
    @pytest.mark.asyncio
    async def test_token_manager_threads_proxy_into_refresh(self):
        from midscene.core.ai_model.service_caller.openai.siwc import (
            credential_storage,
            refresh,
        )

        record = {
            "credentials": {
                "access_token": "old",
                "client_id": "client-1",
                "refresh_token": "refresh-1",
            }
        }
        refresh_mock = AsyncMock(
            return_value={**record["credentials"], "access_token": "new"}
        )
        from midscene.core.ai_model.service_caller.openai.siwc.token_manager import (
            SiwcTokenManager,
        )

        manager = SiwcTokenManager()
        proxy = {"httpProxy": "http://proxy:8080", "socksProxy": None}

        with (
            patch.object(credential_storage, "_read_credentials", lambda: record),
            patch.object(credential_storage, "_save_credentials", lambda _record: None),
            patch.object(refresh, "refresh_siwc_credentials", refresh_mock),
        ):
            token = await manager.refresh_access_token("old", proxy)

        assert token == "new"
        refresh_mock.assert_awaited_once_with(
            record["credentials"], None, {"proxy": proxy}
        )

    @pytest.mark.asyncio
    async def test_exchange_uses_configured_proxy(self):
        from midscene.core import siwc

        captured: dict[str, Any] = {}

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
        from midscene.core.ai_model.service_caller.openai.siwc import network

        with (
            patch.object(siwc.httpx, "AsyncClient", _Client),
            patch.object(network, "_verify_id_token", verify),
        ):
            credentials = await siwc.exchange_siwc_code(
                attempt,
                {"code": "code-1", "client_id": "client-1"},
                None,
                {"proxy": {"httpProxy": "http://proxy:8080", "socksProxy": None}},
            )

        assert captured["proxy"] == "http://proxy:8080"
        assert credentials["subject"] == "subject-1"

    @pytest.mark.asyncio
    async def test_siwc_token_expired_refreshes_once(self):
        from midscene.core.ai_model.models.registry import get_model_runtime
        from midscene.core.ai_model.service_caller import call_ai as caller
        from midscene.core.ai_model.service_caller import model_call

        responses = iter(
            [
                FakeResponse({"error": {"code": "token_expired"}}, status_code=401),
                FakeResponse(_chat_completion_payload()),
            ]
        )
        refresh = AsyncMock(return_value="new-token")

        with (
            patch.object(
                model_call.httpx,
                "AsyncClient",
                lambda *a, **k: _StubAsyncClient(responses),
            ),
            patch.object(caller.siwc_token_manager, "refresh_access_token", refresh),
        ):
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
