"""Synced from upstream packages/cli/tests/unit-test/openai-login.test.ts."""

import pytest


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

