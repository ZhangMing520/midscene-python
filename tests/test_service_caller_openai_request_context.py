"""Synced from upstream packages/core/tests/unit-test/service-caller-openai-error.test.ts
(fetch diagnostics subset)."""

import json
from typing import Any, Dict

import pytest


class FakeResponse:
    def __init__(self, body: str, status_code: int = 200, headers=None):
        self.text = body
        self.status_code = status_code
        self.headers = headers or {}


def _install_fetch(monkeypatch, handler):
    from midscene.core.ai_model.service_caller.openai import (
        openai_request_context as context_module,
    )

    async def fake_fetch(input, init=None):
        return await handler(input, init)

    monkeypatch.setattr(context_module, "_base_fetch", fake_fetch)
    return context_module


class TestOpenAIRequestContext:
    @pytest.mark.asyncio
    async def test_records_non_2xx_raw_response_body_without_changing_the_response(
        self, monkeypatch
    ):
        body = json.dumps({"detail": "model does not exist", "trace_id": "trace_123"})
        response = FakeResponse(
            body,
            422,
            {"content-type": "application/json", "x-request-id": "req_123"},
        )
        context_module = _install_fetch(
            monkeypatch, lambda input, init: _resolve(response)
        )
        context: Dict[str, Any] = {}

        wrapped = await context_module.wrap_open_ai_compatible_fetch(context)(
            "https://example.com/v1/chat/completions", {"method": "POST"}
        )

        assert wrapped is response
        assert context == {
            "responseRequestId": {
                "requestId": "req_123",
                "status": 422,
                "ok": False,
            },
            "rawResponseBody": body,
        }

    @pytest.mark.asyncio
    async def test_does_not_record_successful_response_bodies(self, monkeypatch):
        response = FakeResponse(
            json.dumps({"ok": True}),
            200,
            {"content-type": "application/json"},
        )
        context_module = _install_fetch(
            monkeypatch, lambda input, init: _resolve(response)
        )
        context: Dict[str, Any] = {}

        wrapped = await context_module.wrap_open_ai_compatible_fetch(context)(
            "https://example.com"
        )

        assert wrapped is response
        assert context == {}

    @pytest.mark.asyncio
    async def test_does_not_include_request_headers_in_record_events(
        self, monkeypatch
    ):
        response = FakeResponse("", 200, {})
        context_module = _install_fetch(
            monkeypatch, lambda input, init: _resolve(response)
        )
        events = []
        context = {"recordEvent": events.append}
        body = json.dumps({"model": "example-model"})

        await context_module.wrap_open_ai_compatible_fetch(context)(
            "https://example.com",
            {
                "method": "POST",
                "headers": {"authorization": "Bearer secret-api-key"},
                "body": body,
            },
        )

        assert events == [
            {
                "type": "request",
                "request": {
                    "url": "https://example.com",
                    "method": "POST",
                    "body": body,
                },
            }
        ]
        assert "secret-api-key" not in json.dumps(events)

    @pytest.mark.asyncio
    async def test_records_and_reports_original_fetch_errors_before_rethrowing(
        self, monkeypatch
    ):
        class ConnectTimeoutError(RuntimeError):
            code = "UND_ERR_CONNECT_TIMEOUT"

        cause = ConnectTimeoutError(
            "Connect Timeout Error (attempted addresses: 2605:340::1:443, "
            "timeout: 10000ms)"
        )
        fetch_error = TypeError("fetch failed")
        fetch_error.__cause__ = cause

        async def raise_fetch(input, init=None):
            raise fetch_error

        context_module = _install_fetch(monkeypatch, raise_fetch)
        context: Dict[str, Any] = {}

        with pytest.raises(TypeError) as exc_info:
            await context_module.wrap_open_ai_compatible_fetch(context)(
                "https://example.com"
            )

        assert exc_info.value is fetch_error
        assert context["fetchError"] == (
            "TypeError: fetch failed\n"
            "Cause: ConnectTimeoutError [UND_ERR_CONNECT_TIMEOUT]: "
            "Connect Timeout Error (attempted addresses: 2605:340::1:443, "
            "timeout: 10000ms)"
        )
        assert "OpenAI fetch error: TypeError: fetch failed\nCause: " in (
            context_module.format_open_aiapi_error_details(fetch_error, context)
        )

    @pytest.mark.asyncio
    async def test_keeps_request_details_isolated_between_attempts(
        self, monkeypatch
    ):
        responses = [
            FakeResponse("first failure", 500, {"x-request-id": "first_request"}),
            FakeResponse("second failure", 502),
        ]
        calls = iter(responses)

        async def handler(input, init=None):
            return next(calls)

        context_module = _install_fetch(monkeypatch, handler)
        first_context: Dict[str, Any] = {}
        second_context: Dict[str, Any] = {}

        await context_module.wrap_open_ai_compatible_fetch(first_context)(
            "https://example.com"
        )
        await context_module.wrap_open_ai_compatible_fetch(second_context)(
            "https://example.com"
        )

        assert first_context == {
            "rawResponseBody": "first failure",
            "responseRequestId": {
                "requestId": "first_request",
                "status": 500,
                "ok": False,
            },
        }
        assert second_context == {"rawResponseBody": "second failure"}
        assert context_module.format_open_aiapi_error_details(
            None, second_context
        ) == "\nOpenAI raw error response body: second failure"

    @pytest.mark.asyncio
    async def test_records_http_response_and_error_event_for_non_2xx(
        self, monkeypatch
    ):
        response = FakeResponse(
            "temporary failure", 500, {"content-type": "application/json"}
        )
        context_module = _install_fetch(
            monkeypatch, lambda input, init: _resolve(response)
        )
        events = []
        context = {"recordEvent": events.append}

        await context_module.wrap_open_ai_compatible_fetch(context)(
            "https://example.com"
        )

        assert context["httpResponse"] == {
            "status": 500,
            "ok": False,
            "headers": [("content-type", "application/json")],
            "body": "temporary failure",
        }
        assert events[-1]["type"] == "error"
        assert events[-1]["status"] == 500


async def _resolve(value):
    return value
