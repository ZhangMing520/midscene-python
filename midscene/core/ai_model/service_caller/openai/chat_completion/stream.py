"""Streaming chat-completion parsing (upstream chat-completion/stream.ts)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from midscene.core.ai_model.service_caller.openai.chat_completion.utils import (
    resolve_content_with_reasoning_fallback,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.utils import (
    emit_stream_chunk,
    has_usable_text,
)


async def call_chat_completion_stream(
    lines: AsyncIterator[str],
    adapter: Any,
    on_chunk: Any | None = None,
) -> dict[str, Any]:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    accumulated = ""
    accumulated_reasoning = ""
    usage: dict[str, Any] | None = None
    response_model: str | None = None

    async for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = event.get("choices")
        if not choices:
            if event.get("usage"):
                usage = event["usage"]
            if event.get("model"):
                response_model = event["model"]
            continue
        delta = choices[0].get("delta") or {}
        content_piece = ""
        piece = delta.get("content")
        if isinstance(piece, str):
            content_piece = piece
            content_parts.append(piece)
        elif isinstance(piece, list):
            text_parts = [
                part.get("text", "")
                for part in piece
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content_piece = "".join(text_parts)
            content_parts.extend(text_parts)
        reasoning_piece = ""
        for key in ("reasoning_content", "reasoning"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                reasoning_piece += value
                reasoning_parts.append(value)
        if content_piece or reasoning_piece:
            accumulated += content_piece
            accumulated_reasoning += reasoning_piece
            await emit_stream_chunk(
                on_chunk, content_piece, reasoning_piece, accumulated
            )
        if event.get("usage"):
            usage = event["usage"]
        if event.get("model"):
            response_model = event["model"]

    content = "".join(content_parts)
    reasoning_content = "".join(reasoning_parts)
    final_content = resolve_content_with_reasoning_fallback(
        content,
        reasoning_content,
        adapter.use_reasoning_as_content_fallback,
    )
    await emit_stream_chunk(on_chunk, "", "", final_content or accumulated, True, usage)
    raw_assistant_output = {
        "type": "chat-completion",
        "rawValue": {
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning_content,
        },
    }
    if not has_usable_text(final_content):
        raise AIResponseParseError(
            "empty content from AI model",
            final_content or "",
            usage,
            raw_assistant_output,
        )
    return {
        "content": final_content,
        "reasoningContent": reasoning_content,
        "rawAssistantOutput": raw_assistant_output,
        "rawUsage": usage,
        "requestId": None,
        "responseModelName": response_model,
    }
