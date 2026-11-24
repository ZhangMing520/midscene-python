"""OpenAI transport factory and proxy resolution helpers."""

import pytest


class TestCreateClient:
    @pytest.mark.asyncio
    async def test_builds_transport_with_midscene_headers_and_context(self):
        from midscene.core.ai_model.service_caller.openai.openai_client import (
            create_client,
        )

        events = []
        result = await create_client(
            {
                "modelConfig": {
                    "openaiBaseURL": "https://api.example.com/v1/",
                    "openaiApiKey": "sk-test",
                    "openaiExtraConfig": {"defaultHeaders": {"x-provider": "value"}},
                },
                "effectiveTimeoutMs": 5000,
                "executionId": "exec-1",
                "recordEvent": events.append,
            }
        )
        client = result["openai"]
        try:
            assert str(client.base_url) == "https://api.example.com/v1/"
            assert client.headers["authorization"] == "Bearer sk-test"
            assert client.headers["x-provider"] == "value"
            assert client.headers["x-midscene-execution-id"] == "exec-1"
            assert client.timeout.read == 5.0
            assert result["openAIRequestContext"] == {"recordEvent": events.append}
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_omits_timeout_when_the_hard_timeout_is_disabled(self):
        from midscene.core.ai_model.service_caller.openai.openai_client import (
            create_client,
        )

        result = await create_client(
            {
                "modelConfig": {
                    "openaiBaseURL": "https://api.example.com/v1",
                    "openaiApiKey": "sk-test",
                },
                "effectiveTimeoutMs": None,
                "executionId": "exec-1",
            }
        )
        client = result["openai"]
        try:
            # httpx keeps its default timeout when Midscene disables its own.
            assert client.timeout.read == 5.0
        finally:
            await client.aclose()


class TestProxy:
    def test_prefers_http_proxy_over_socks(self):
        from midscene.core.ai_model.service_caller.proxy.proxy import (
            create_proxy_agent_if_needed,
        )

        assert (
            create_proxy_agent_if_needed(
                socks_proxy="socks5://localhost:1080",
                http_proxy="http://localhost:7890",
            )
            == "http://localhost:7890"
        )

    def test_returns_socks_proxy_when_it_is_the_only_option(self):
        from midscene.core.ai_model.service_caller.proxy.proxy import (
            create_proxy_agent_if_needed,
        )

        assert (
            create_proxy_agent_if_needed(socks_proxy="socks5://localhost:1080")
            == "socks5://localhost:1080"
        )

    def test_returns_none_without_a_configured_proxy(self):
        from midscene.core.ai_model.service_caller.proxy.proxy import (
            create_proxy_agent_if_needed,
        )

        assert create_proxy_agent_if_needed() is None

    def test_rejects_socks_urls_without_host_or_port(self):
        from midscene.core.ai_model.service_caller.proxy.proxy import (
            create_proxy_agent_if_needed,
        )

        with pytest.raises(ValueError, match="valid hostname"):
            create_proxy_agent_if_needed(socks_proxy="socks5://:1080")
        with pytest.raises(ValueError, match="valid port"):
            create_proxy_agent_if_needed(socks_proxy="socks5://localhost")

    def test_sanitize_proxy_url_hides_the_password(self):
        from midscene.core.ai_model.service_caller.proxy.proxy import (
            sanitize_proxy_url,
        )

        sanitized = sanitize_proxy_url("http://user:secret@proxy:8080")
        assert "secret" not in sanitized
        assert "user" in sanitized
