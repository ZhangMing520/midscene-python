"""OpenAI request diagnostics (upstream openai/openai-request-context.ts)."""

from typing import Any, Dict, Optional, TypedDict

MAX_ERROR_RESPONSE_BODY_LENGTH = 4000
MAX_FETCH_ERROR_LENGTH = 4000


class OpenAIRequestContext(TypedDict, total=False):
    rawResponseBody: str
    fetchError: str
    responseRequestId: Dict[str, Any]
    httpResponse: Dict[str, Any]


def truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}... [truncated, {len(text)} chars total]"


def format_fetch_error(error: BaseException) -> str:
    details = [f"{type(error).__name__}: {error}"]
    cause = error.__cause__
    if cause is not None:
        details.append(f"Cause: {type(cause).__name__}: {cause}")
    return truncate_text("\n".join(details), MAX_FETCH_ERROR_LENGTH)


def format_openai_api_error_details(
    _error: BaseException,
    context: OpenAIRequestContext,
) -> str:
    details = []
    raw_response_body = context.get("rawResponseBody")
    if raw_response_body is not None:
        details.append(
            "OpenAI raw error response body: "
            f"{truncate_text(raw_response_body, MAX_ERROR_RESPONSE_BODY_LENGTH)}"
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


def request_id_from_headers(headers: Any) -> Optional[str]:
    return headers.get("x-request-id") or headers.get("x-model-request-id")
