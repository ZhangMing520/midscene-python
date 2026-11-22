"""Synced from upstream packages/cli/tests/unit-test/openai-login.test.ts."""

import asyncio
import socket
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from midscene.cli.openai import login as login_module


def _get_status(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


async def _get(url):
    return await asyncio.to_thread(_get_status, url)


def _fake_exchange(attempt, callback):
    return {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "openid chatgpt.tokens.use.direct",
        "id_token": "header.payload.signature",
        "subject": "test-user",
        "ext_agent_host_id": attempt["host_id"],
        "client_id": callback["client_id"],
    }


def _callback_url(authorization_url, **overrides):
    parsed = urlparse(authorization_url)
    query = parse_qs(parsed.query)
    callback = urlparse(query["redirect_uri"][0])
    params = {
        "state": query["state"][0],
        "code": "test-code",
        "client_id": "oaiapp_test",
    }
    params.update(overrides)
    from urllib.parse import urlencode

    return f"{callback.scheme}://{callback.netloc}{callback.path}?{urlencode(params)}"


class TestSiwcAuthorization:
    def test_authorization_url_contains_pkce(self):
        from midscene.core.siwc import create_siwc_authorization

        auth = create_siwc_authorization(
            "urn:uuid:test", "http://127.0.0.1:9999/auth/callback"
        )
        assert "code_challenge_method=S256" in auth["url"]
        assert "chatgpt.tokens.use.direct" in auth["url"]

    def test_parse_callback_validates_state(self):
        from midscene.core.siwc import (
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
        from midscene.core.siwc import (
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


_SIWC_MODULE = (
    "midscene.core.ai_model.service_caller.openai.siwc.authorization"
)


def test_loopback_login_returns_credentials_and_closes_the_server(
    monkeypatch,
):
    """uses PKCE, ignores invalid callbacks, returns verified credentials and closes the server"""
    exchange_calls = []
    seen = {}

    async def fake_exchange(attempt, callback):
        exchange_calls.append(callback)
        return _fake_exchange(attempt, callback)

    monkeypatch.setattr(f"{_SIWC_MODULE}.exchange_siwc_code", fake_exchange)

    async def on_authorization(url):
        seen["url"] = url
        query = parse_qs(urlparse(url).query)
        assert query["client_id"][0] == "dynamic_agent_client"
        callback = _callback_url(url)
        base = callback.split("/auth/callback")[0]

        assert await _get(_callback_url(url, state="wrong")) == 400
        assert await _get(f"{base}/favicon.ico") == 404
        assert await _get(callback) == 200
        assert await _get(callback) == 409

    result = asyncio.run(
        login_module.login_with_openai({"onAuthorization": on_authorization})
    )

    assert result["access_token"] == "access-secret"
    assert result["subject"] == "test-user"
    assert result["ext_agent_host_id"].startswith("urn:uuid:")
    assert len(exchange_calls) == 1

    base = _callback_url(seen["url"]).split("/auth/callback")[0]
    with pytest.raises(Exception):
        asyncio.run(_get(f"{base}/auth/callback"))


def test_handles_denial_without_exchanging_a_code(monkeypatch):
    """handles denial without exchanging a code"""
    exchange_calls = []

    async def fake_exchange(attempt, callback):
        exchange_calls.append(callback)
        return _fake_exchange(attempt, callback)

    monkeypatch.setattr(f"{_SIWC_MODULE}.exchange_siwc_code", fake_exchange)

    async def on_authorization(url):
        callback = _callback_url(url, error="access_denied")
        assert await _get(callback) == 400

    with pytest.raises(Exception) as info:
        asyncio.run(
            login_module.login_with_openai(
                {"onAuthorization": on_authorization}
            )
        )

    message = str(info.value)
    assert "Stage: Authorization callback" in message
    assert "denied" in message
    assert exchange_calls == []


def test_rejects_occupied_ports_without_hanging():
    """rejects occupied ports without hanging"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    launched = []

    async def on_authorization(_url):
        launched.append(True)

    try:
        with pytest.raises(Exception):
            asyncio.run(
                login_module.login_with_openai(
                    {"port": port, "onAuthorization": on_authorization}
                )
            )
    finally:
        server.close()

    assert launched == []


def test_closes_the_listener_when_cancelled():
    """closes the listener when cancelled"""

    class Signal:
        aborted = False

    signal = Signal()
    seen = {}

    async def on_authorization(url):
        seen["url"] = url
        signal.aborted = True

    with pytest.raises(Exception) as info:
        asyncio.run(
            login_module.login_with_openai(
                {"signal": signal, "onAuthorization": on_authorization}
            )
        )

    assert "cancelled" in str(info.value)
    with pytest.raises(Exception):
        asyncio.run(_get(_callback_url(seen["url"])))


@pytest.mark.parametrize(
    "failure",
    ["nonce", "issuer", "audience", "signature", "scope", "http"],
)
@pytest.mark.skip(
    reason=(
        "ID-token signature/claim verification and HTTP exchange live in "
        "core exchange_siwc_code; the CLI login port replaces the exchange at "
        "the module boundary rather than accepting injected fetch/keys"
    )
)
def test_does_not_return_credentials_on_failure(failure):
    """does not return credentials on %s failure"""


@pytest.mark.parametrize("clock_mismatch", ["expired", "future"])
@pytest.mark.skip(
    reason=(
        "Clock-skew tolerance is implemented by the core JWT verifier, which "
        "this CLI-layer test does not exercise"
    )
)
def test_accepts_verified_id_token_despite_local_clock_mismatch(clock_mismatch):
    """accepts a verified ID token despite local clock mismatch"""


def test_reuses_supplied_registration_and_host_identifiers(monkeypatch):
    """reuses supplied registration and host identifiers"""
    exchange_calls = []

    async def fake_exchange(attempt, callback):
        exchange_calls.append(callback)
        return _fake_exchange(attempt, callback)

    monkeypatch.setattr(f"{_SIWC_MODULE}.exchange_siwc_code", fake_exchange)

    async def on_authorization(url):
        query = parse_qs(urlparse(url).query)
        assert "agent_name_hint" not in query
        assert query["client_id"][0] == "oaiapp_test"
        assert await _get(_callback_url(url, client_id="other-client")) == 400
        assert await _get(_callback_url(url)) == 200

    result = asyncio.run(
        login_module.login_with_openai(
            {
                "hostId": "urn:uuid:test-host",
                "clientId": "oaiapp_test",
                "onAuthorization": on_authorization,
            }
        )
    )

    assert result["ext_agent_host_id"] == "urn:uuid:test-host"
    assert len(exchange_calls) == 1

