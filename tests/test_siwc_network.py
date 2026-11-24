"""Synced from upstream packages/core/tests/unit-test/siwc-network.test.ts."""

import json
from typing import Any

import pytest

from midscene.core.ai_model.service_caller.openai.siwc.errors import SiwcError
from midscene.core.ai_model.service_caller.openai.siwc.network import (
    create_siwc_jwk_set,
    fetch_siwc,
)


class FakeResponse:
    def __init__(self, payload: Any = None, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


def _install_client(monkeypatch, response: FakeResponse) -> list[dict[str, Any]]:
    from midscene.core.ai_model.service_caller.openai.siwc import network

    captured: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            captured.append({"method": method, "url": url, **kwargs})
            return response

    monkeypatch.setattr(network.httpx, "AsyncClient", FakeAsyncClient)
    return captured


class TestSiwcNetwork:
    @pytest.mark.asyncio
    async def test_prioritizes_the_midscene_http_proxy_over_socks(self, monkeypatch):
        captured = _install_client(monkeypatch, FakeResponse())
        monkeypatch.setenv("MIDSCENE_MODEL_HTTP_PROXY", "http://localhost:17890")
        monkeypatch.setenv("MIDSCENE_MODEL_SOCKS_PROXY", "socks5://localhost:1080")
        monkeypatch.setenv("HTTPS_PROXY", "http://localhost:7890")

        await fetch_siwc(
            "https://auth.openai.com/api/accounts/oauth/token", {"method": "POST"}
        )

        # Generic environment proxies are ignored unless configured explicitly.
        assert captured[0]["proxy"] == "http://localhost:17890"
        assert captured[0]["trust_env"] is False
        assert captured[1]["method"] == "POST"

    @pytest.mark.asyncio
    async def test_uses_the_midscene_socks_proxy(self, monkeypatch):
        captured = _install_client(monkeypatch, FakeResponse())
        monkeypatch.setenv("MIDSCENE_MODEL_SOCKS_PROXY", "socks5://localhost:1080")
        monkeypatch.setenv("HTTP_PROXY", "http://localhost:7891")

        await fetch_siwc("https://auth.openai.com")

        assert captured[0]["proxy"] == "socks5://localhost:1080"
        assert captured[0]["trust_env"] is False

    @pytest.mark.asyncio
    async def test_does_not_create_a_proxy_from_generic_environment_variables(
        self, monkeypatch
    ):
        captured = _install_client(monkeypatch, FakeResponse())
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(key, "http://localhost:7890")

        await fetch_siwc("https://auth.openai.com")

        assert captured[0]["proxy"] is None
        assert captured[0]["trust_env"] is True

    @pytest.mark.asyncio
    async def test_downloads_jwks_and_reports_http_failures(self):
        signal = object()

        async def request(url, init):
            assert url == "https://auth.openai.com/.well-known/jwks.json"
            assert init == {"signal": signal, "redirect": "error"}
            return FakeResponse(status_code=503)

        resolve = create_siwc_jwk_set("https://auth.openai.com", signal, request)
        with pytest.raises(SiwcError, match="HTTP 503"):
            await resolve({"alg": "RS256"}, {"payload": "", "signature": ""})

    @pytest.mark.asyncio
    async def test_verifies_signatures_with_keys_fetched_through_the_injected_request(
        self,
    ):
        pytest.importorskip("jwt", reason="PyJWT is not installed in this environment")
        pytest.importorskip(
            "cryptography",
            reason="cryptography (PyJWT crypto extra) is not installed",
        )
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
        public_jwk["kid"] = "test"

        token = jwt.encode(
            {"sub": "user"},
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            algorithm="RS256",
            headers={"kid": "test"},
        )

        async def request(url, init):
            return FakeResponse({"keys": [public_jwk]})

        resolve = create_siwc_jwk_set("https://auth.openai.com", object(), request)
        jwk = await resolve({"alg": "RS256", "kid": "test"}, token)
        payload = jwt.decode(token, jwk.key, algorithms=["RS256"])

        assert payload["sub"] == "user"
