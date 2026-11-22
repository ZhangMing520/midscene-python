"""Synced from upstream packages/core/tests/unit-test/siwc-network.test.ts."""

from typing import Any, Dict
from unittest.mock import patch

import pytest

from tests.core_helpers import FakeResponse


class TestSiwcNetworkProxy:
    def test_resolve_proxy_precedence(self, monkeypatch):
        from midscene.core.siwc import _siwc_proxy

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
        from midscene.core import siwc

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
        from midscene.core import siwc

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

