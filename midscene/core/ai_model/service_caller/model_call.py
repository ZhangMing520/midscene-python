"""Legacy transport import surface.

The transport now lives in ``service_caller.openai`` (upstream
``openai/openai-client.ts`` and the protocol call modules). This module keeps
the historical ``service_caller.model_call`` imports working.
"""

from typing import Any, AsyncIterator, Dict, Optional
import json

import httpx  # noqa: F401  (kept so tests can patch ``model_call.httpx``)

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


class _NoFallbackAdapter:
    use_reasoning_as_content_fallback = False


async def _aggregate_stream_lines(
    lines: AsyncIterator[str], on_chunk: Optional[Any] = None
) -> Dict[str, Any]:
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
    return await call_chat_completion_stream(
        replayed(), _NoFallbackAdapter(), on_chunk
    )


__all__ = [
    "_aggregate_stream_lines",
    "_post_json",
    "_request_headers",
    "call_openai",
    "post_json",
    "request_headers",
    "stream_lines",
]
