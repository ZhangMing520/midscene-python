"""HTTP transport for OpenAI-compatible endpoints.

Upstream uses the official OpenAI SDK (``openai/openai-client.ts``); the
Python SDK talks to the same wire protocol over httpx.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from midscene.core.ai_model.service_caller.openai import openai_request_context
from midscene.core.ai_model.service_caller.openai.siwc.errors import (
    SiwcTokenExpiredError,
)


def resolve_endpoint(model_config: dict[str, Any], protocol: str) -> str:
    base_url = (
        model_config.get("openaiBaseURL") or "https://api.openai.com/v1"
    ).rstrip("/")
    if protocol == "openai-responses":
        return f"{base_url}/responses"
    return f"{base_url}/chat/completions"


def request_headers(
    model_config: dict[str, Any],
    execution_id: str | None = None,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = model_config.get("openaiApiKey")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    extra_config = model_config.get("openaiExtraConfig") or {}
    extra_headers = (
        extra_config.get("defaultHeaders")
        or extra_config.get("extraHeaders")
        or extra_config.get("extra_headers")
    )
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    # Midscene-owned headers override user-supplied ones with the same name.
    headers["x-midscene-version"] = __import__("midscene").__version__
    if execution_id:
        headers["x-midscene-execution-id"] = execution_id
    return headers


def resolve_proxy(model_config: dict[str, Any]) -> str | None:
    from midscene.core.ai_model.service_caller.proxy.proxy import (
        resolve_proxy_agent,
    )

    return resolve_proxy_agent(
        socks_proxy=model_config.get("socksProxy"),
        http_proxy=model_config.get("httpProxy"),
    )


def _timeout_seconds(effective_timeout: float | None) -> float | None:
    return effective_timeout / 1000 if effective_timeout is not None else None


def _is_siwc_token_expired(status_code: int, body: str) -> bool:
    if status_code != 401:
        return False
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    return isinstance(error, dict) and error.get("code") == "token_expired"


def _raise_http_error(
    status_code: int,
    body: str,
    context: openai_request_context.OpenAIRequestContext | None = None,
) -> None:
    if _is_siwc_token_expired(status_code, body):
        raise SiwcTokenExpiredError(body[:2000])
    details = openai_request_context.format_open_aiapi_error_details(
        None, context or {}
    )
    raise RuntimeError(
        f"LLM service response error, status: {status_code}, body: {body[:2000]}"
        f"{details}"
    )


def _context_for_response(
    response: httpx.Response, body: str | None = None
) -> openai_request_context.OpenAIRequestContext:
    request_id = openai_request_context.request_id_from_headers(response.headers)
    ok = response.status_code < 400
    context: openai_request_context.OpenAIRequestContext = {
        "httpResponse": {
            "status": response.status_code,
            "ok": ok,
            "headers": list(response.headers.items()),
            **({} if body is None else {"body": body}),
        }
    }
    if body is not None and not ok:
        context["rawResponseBody"] = body
    if request_id:
        context["responseRequestId"] = {
            "requestId": request_id,
            "status": response.status_code,
            "ok": ok,
        }
    return context


async def post_json(
    url: str,
    headers: dict[str, str],
    request_body: dict[str, Any],
    effective_timeout: float | None,
    proxy: str | None,
    stream: bool = False,
    on_chunk: Any | None = None,
    record_event: Any | None = None,
) -> Any:
    """POST a JSON body and return parsed JSON (or an aggregated stream)."""
    if stream:
        # Legacy unified entry; the protocol modules consume SSE frames directly.
        from midscene.core.ai_model.service_caller.model_call import (
            _aggregate_stream_lines,
        )

        return await _aggregate_stream_lines(
            stream_lines(
                url,
                headers,
                request_body,
                effective_timeout,
                proxy,
                record_event=record_event,
            ),
            on_chunk,
        )

    timeout_seconds = _timeout_seconds(effective_timeout)
    timeout = httpx.Timeout(timeout_seconds) if timeout_seconds else None
    if record_event:
        record_event(
            {
                "type": "request",
                "request": {"url": url, "method": "POST", "body": request_body},
            }
        )
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            response = await client.post(url, headers=headers, json=request_body)
    except httpx.TimeoutException as e:
        if record_event:
            record_event(
                {"type": "error", "error": f"timeout after {effective_timeout}ms"}
            )
        raise RuntimeError(f"model request timeout after {effective_timeout}ms") from e
    except httpx.HTTPError as e:
        fetch_error = openai_request_context.format_fetch_error(e)
        if record_event:
            record_event({"type": "error", "error": fetch_error})
        raise RuntimeError(f"OpenAI fetch error: {fetch_error}") from e

    body = response.text
    if response.status_code >= 400:
        _raise_http_error(
            response.status_code, body, _context_for_response(response, body)
        )
    try:
        return response.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON response from LLM service: {e}") from e


async def stream_lines(
    url: str,
    headers: dict[str, str],
    request_body: dict[str, Any],
    effective_timeout: float | None,
    proxy: str | None,
    record_event: Any | None = None,
) -> AsyncIterator[str]:
    """Yield SSE lines from a streaming request."""
    timeout_seconds = _timeout_seconds(effective_timeout)
    timeout = httpx.Timeout(timeout_seconds) if timeout_seconds else None
    if record_event:
        record_event(
            {
                "type": "request",
                "request": {"url": url, "method": "POST", "body": request_body},
            }
        )
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json={**request_body, "stream": True},
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "ignore")
                    _raise_http_error(
                        response.status_code,
                        body,
                        _context_for_response(response, body),
                    )
                async for line in response.aiter_lines():
                    yield line
    except httpx.TimeoutException as e:
        if record_event:
            record_event(
                {"type": "error", "error": f"timeout after {effective_timeout}ms"}
            )
        raise RuntimeError(f"model request timeout after {effective_timeout}ms") from e
    except httpx.HTTPError as e:
        fetch_error = openai_request_context.format_fetch_error(e)
        if record_event:
            record_event({"type": "error", "error": fetch_error})
        raise RuntimeError(f"OpenAI fetch error: {fetch_error}") from e


async def create_client(options: dict[str, Any]) -> dict[str, Any]:
    """Create the HTTP transport and request-diagnostics context.

    Upstream builds an OpenAI SDK client; the Python SDK talks to the same wire
    protocol through httpx, so ``openai`` holds an ``httpx.AsyncClient``.
    """
    model_config = _client_option(options, "modelConfig", "model_config") or {}
    record_event = _client_option(options, "recordEvent", "record_event")
    execution_id = _client_option(options, "executionId", "execution_id")
    effective_timeout = _client_option(
        options, "effectiveTimeoutMs", "effective_timeout_ms"
    )

    context: openai_request_context.OpenAIRequestContext = {}
    if record_event is not None:
        context["recordEvent"] = record_event

    base_url = (
        model_config.get("openaiBaseURL") or "https://api.openai.com/v1"
    ).rstrip("/")
    client_kwargs: dict[str, Any] = {
        "base_url": base_url,
        "headers": request_headers(model_config, execution_id),
        "proxy": resolve_proxy(model_config),
    }
    if effective_timeout is not None:
        client_kwargs["timeout"] = httpx.Timeout(effective_timeout / 1000)

    return {
        "openai": httpx.AsyncClient(**client_kwargs),
        "openAIRequestContext": context,
    }


def _client_option(options: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in options:
            return options[key]
    return default


# Backwards-compatible aliases for the pre-split helper names.
_post_json = post_json
_request_headers = request_headers
