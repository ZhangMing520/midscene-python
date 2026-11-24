"""Streaming Responses parsing (upstream responses/stream.ts)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from midscene.core.ai_model.service_caller.openai.responses.utils import parse_response
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.utils import (
    emit_stream_chunk,
    has_usable_text,
)


async def call_responses_stream(
    lines: AsyncIterator[str],
    on_chunk: Any | None = None,
) -> dict[str, Any]:
    accumulated = ""
    final_response: dict[str, Any] | None = None
    completed_items: dict[int, dict[str, Any]] = {}

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
        event_type = event.get("type") or ""
        if event_type == "error":
            raise RuntimeError(
                f"Responses stream error: {event.get('error') or event.get('message')}"
            )
        if event_type in ("response.failed", "response.incomplete"):
            # parse_response raises with the failure reason.
            parse_response(event.get("response") or {})
        if event_type == "response.output_item.done":
            item = event.get("item")
            if item:
                completed_items[event.get("output_index", 0)] = item
        if event_type == "response.completed":
            final_response = event.get("response") or {}

        content = (
            event.get("delta", "") or ""
            if event_type == "response.output_text.delta"
            else ""
        )
        reasoning_content = (
            event.get("delta", "") or ""
            if event_type
            in (
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            )
            else ""
        )
        if content or reasoning_content:
            accumulated += content
            await emit_stream_chunk(on_chunk, content, reasoning_content, accumulated)

    if final_response is None:
        raise RuntimeError("Responses stream ended without a response.completed event")
    payload = {"status": "completed", **final_response}
    # Some ChatGPT plan responses omit output from the completion event even
    # after delivering complete items. Preserve those items without treating
    # an interrupted stream as complete.
    if not payload.get("output"):
        payload = {
            **payload,
            "output": [completed_items[index] for index in sorted(completed_items)],
        }
    result = parse_response(payload)
    if not has_usable_text(result["content"]):
        raise AIResponseParseError(
            "empty content from AI model",
            result["content"],
            None,
            result["rawAssistantOutput"],
        )
    await emit_stream_chunk(
        on_chunk, "", "", result["content"], True, result.get("rawUsage")
    )
    return {**result, "requestId": payload.get("id")}
