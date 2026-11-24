"""Legacy transport import surface.

The transport now lives in ``service_caller.openai`` (upstream
``openai/openai-client.ts`` and the protocol call modules). This module keeps
the historical ``service_caller.model_call`` imports working.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx  # noqa: F401  (kept so tests can patch ``model_call.httpx``)

from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
    call_generative_ai,
)
from midscene.core.ai_model.service_caller.openai.call_openai import call_openai
from midscene.core.ai_model.service_caller.openai.chat_completion.stream import (
    call_chat_completion_stream,
)
from midscene.core.ai_model.service_caller.openai.openai_client import (  # noqa: F401
    _post_json,
    _request_headers,
    post_json,
    request_headers,
    stream_lines,
)
from midscene.core.ai_model.service_caller.openai.responses.stream import (
    call_responses_stream,
)
from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.shared.json import (
    assert_json_object,
    parse_model_response_json,
)


class _NoFallbackAdapter:
    use_reasoning_as_content_fallback = False


async def _aggregate_stream_lines(
    lines: AsyncIterator[str], on_chunk: Any | None = None
) -> dict[str, Any]:
    """Aggregate a chat-completion or Responses SSE stream.

    The protocol is detected from the first typed event so the result matches
    the split protocol modules while preserving the pre-split helper.
    """
    iterator = lines.__aiter__()
    buffered = []
    protocol = None
    while True:
        try:
            line = await iterator.__anext__()
        except StopAsyncIteration:
            break
        buffered.append(line)
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or ""
        if event_type.startswith("response.") or "response" in event:
            protocol = "responses"
        elif "choices" in event:
            protocol = "chat-completion"
        if protocol:
            break

    async def replayed() -> AsyncIterator[str]:
        for item in buffered:
            yield item
        async for item in iterator:
            yield item

    if protocol == "responses":
        return await call_responses_stream(replayed(), on_chunk)
    return await call_chat_completion_stream(replayed(), _NoFallbackAdapter(), on_chunk)


def parse_ai_object_response(
    response: dict[str, Any],
    model_runtime: Any,
    json_parser_source: str = "generic-object",
) -> dict[str, Any]:
    """Parse an AI string response into a JSON object (upstream model-call.ts)."""
    if not response:
        raise ValueError("empty response")
    content = response.get("content") or ""
    parser = model_runtime.adapter.json_parser
    parsed = (
        parser(content, source=json_parser_source)
        if parser is not None
        else parse_model_response_json(content, source=json_parser_source)
    )
    assert_json_object(parsed)
    return {
        "content": parsed,
        "contentString": content,
        "usage": response.get("usage"),
        "reasoning_content": response.get("reasoning_content"),
        "rawAssistantOutput": response.get("rawAssistantOutput"),
    }


async def call_ai_with_object_response(
    messages: list[dict],
    model_runtime: Any,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the model expecting a JSON object response."""
    options = options or {}
    model_config = model_runtime.config
    json_parser_source = options.get("jsonParserSource") or "generic-object"

    async def call_ai(retry_attempt: int, previous_error: Any | None) -> dict[str, Any]:
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_error),
            model_runtime,
            {
                "expectedJsonObjectResponse": True,
                "semanticRetryAttempt": retry_attempt,
            },
        )

    def parse_response(response: dict[str, Any]) -> dict[str, Any]:
        return parse_ai_object_response(response, model_runtime, json_parser_source)

    def to_parse_error(
        error: Exception, response: dict[str, Any]
    ) -> AIResponseParseError:
        return AIResponseParseError(
            str(error),
            response.get("content") or "",
            response.get("usage"),
            response.get("rawAssistantOutput"),
            response.get("reasoning_content"),
        )

    return await call_ai_and_parse_with_retry(
        call_ai,
        parse_response,
        to_parse_error,
        parse_retry_times=options.get(
            "retryTimes", model_config.get("retryCount") or 0
        ),
        parse_retry_interval=options.get(
            "retryInterval", model_config.get("retryInterval") or 0
        ),
    )


__all__ = [
    "_aggregate_stream_lines",
    "_post_json",
    "_request_headers",
    "call_ai_with_object_response",
    "call_ai_with_string_response",
    "call_openai",
    "parse_ai_object_response",
    "post_json",
    "request_headers",
    "stream_lines",
]
