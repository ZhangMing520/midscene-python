"""OpenAI request diagnostics (upstream openai/openai-request-context.ts)."""

from typing import Any, Dict, Optional, TypedDict
import json

import httpx
from loguru import logger

MAX_ERROR_RESPONSE_BODY_LENGTH = 4000
MAX_FETCH_ERROR_LENGTH = 4000


class OpenAIRequestContext(TypedDict, total=False):
    recordEvent: Any
    rawResponseBody: str
    fetchError: str
    responseRequestId: Dict[str, Any]
    httpResponse: Dict[str, Any]


def truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}... [truncated, {len(text)} chars total]"


def truncate_error_response_body(body: str) -> str:
    return truncate_text(body, MAX_ERROR_RESPONSE_BODY_LENGTH)


def _get_error_code(error: Any) -> Optional[str]:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else None


def _format_error_summary(error: Any) -> str:
    if isinstance(error, BaseException):
        code = _get_error_code(error)
        code_text = f" [{code}]" if code else ""
        return f"{type(error).__name__}{code_text}: {error}"
    return str(error)


def format_fetch_error(error: BaseException) -> str:
    details = [_format_error_summary(error)]
    cause = getattr(error, "__cause__", None)
    if cause is not None:
        details.append(f"Cause: {_format_error_summary(cause)}")
    return truncate_text("\n".join(details), MAX_FETCH_ERROR_LENGTH)


def format_open_aiapi_error_details(
    _error: Any,
    context: OpenAIRequestContext,
) -> str:
    """Render the diagnostics captured by the fetch wrapper."""
    details = []

    raw_response_body = context.get("rawResponseBody")
    if raw_response_body is not None:
        details.append(
            "OpenAI raw error response body: "
            f"{truncate_error_response_body(raw_response_body)}"
        )

    request_id = context.get("responseRequestId")
    if request_id and not request_id.get("ok"):
        details.append(
            "OpenAI error response request ID "
            f"(status {request_id.get('status')}): {request_id.get('requestId')}"
        )

    fetch_error = context.get("fetchError")
    if fetch_error is not None:
        details.append(f"OpenAI fetch error: {fetch_error}")

    if not details:
        return ""
    return "\n" + "\n".join(details)


# Readable alias for Python callers; the API scanner derives the upstream name.
format_openai_api_error_details = format_open_aiapi_error_details


def request_id_from_headers(headers: Any) -> Optional[str]:
    return headers.get("x-request-id") or headers.get("x-model-request-id")


def _request_body(init: Dict[str, Any]) -> Optional[str]:
    body = init.get("body")
    if body is not None:
        return body if isinstance(body, str) else str(body)
    json_body = init.get("json")
    if json_body is not None:
        return json.dumps(json_body)
    return None


async def _default_fetch(input: Any, init: Optional[Dict[str, Any]] = None):
    """Python transport used when no base fetch is injected."""
    init = dict(init or {})
    method = (init.get("method") or "GET").upper()
    async with httpx.AsyncClient(timeout=init.get("timeout")) as client:
        return await client.request(
            method,
            input if isinstance(input, str) else str(input),
            headers=init.get("headers"),
            content=init.get("body"),
            json=init.get("json"),
        )


# Tests and advanced callers can replace the transport without changing the
# single-argument wrapper contract.
_base_fetch = _default_fetch


def wrap_open_ai_compatible_fetch(context: OpenAIRequestContext):
    """Return a fetch-analog that records request/response diagnostics."""

    async def wrapped(input: Any, init: Optional[Dict[str, Any]] = None):
        init = dict(init or {})
        url = input if isinstance(input, str) else str(input)
        method = init.get("method") or "GET"
        body = _request_body(init)

        record_event = context.get("recordEvent")
        if record_event:
            record_event(
                {
                    "type": "request",
                    "request": {"url": url, "method": method, "body": body},
                }
            )

        try:
            response = await _base_fetch(url, init)
        except BaseException as error:
            fetch_error_summary = format_fetch_error(error)
            logger.debug(f"OpenAI-compatible fetch failed: {fetch_error_summary}")
            context["fetchError"] = fetch_error_summary
            if record_event:
                record_event({"type": "error", "error": fetch_error_summary})
            raise

        status = response.status_code
        ok = status < 400
        request_id = request_id_from_headers(response.headers)
        if request_id:
            context["responseRequestId"] = {
                "requestId": request_id,
                "status": status,
                "ok": ok,
            }

        if not ok:
            context["rawResponseBody"] = response.text

        if record_event:
            content_type = response.headers.get("content-type") or ""
            is_stream = "text/event-stream" in content_type
            http_response: Dict[str, Any] = {
                "status": status,
                "ok": ok,
                "headers": list(response.headers.items()),
            }
            if not is_stream:
                http_response["body"] = response.text
            context["httpResponse"] = http_response
            if not ok:
                record_event({"type": "error", **http_response})

        return response

    return wrapped
