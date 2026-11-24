"""Responses input/usage/parse helpers (upstream responses/utils.ts)."""

from typing import Any

from midscene.core.ai_model.service_caller.openai.chat_completion.utils import (
    ensure_data_url,
)


def to_responses_input(messages: list[dict], image_detail: str) -> list[dict]:
    """Convert internal messages to the Responses API input format.

    Conversation-history entries (``input-message`` / ``model-output``) are
    flattened to input items first, matching upstream ``toResponsesInput``.
    """
    input_items: list[dict] = []
    for entry in messages:
        if entry.get("type") == "model-output" and "output" in entry:
            output = entry.get("output") or {}
            if output.get("type") != "responses":
                raise ValueError(
                    "Cannot replay Chat Completions output in a Responses conversation"
                )
            input_items.extend(output.get("rawValue") or [])
            continue
        message = entry["message"] if entry.get("type") == "input-message" else entry
        content = message.get("content")
        if isinstance(content, str):
            input_items.append({"role": message["role"], "content": content})
            continue
        if message["role"] == "assistant":
            text = "".join(part.get("text", "") for part in content or [])
            input_items.append({"role": "assistant", "content": text})
            continue
        parts: list[dict] = []
        for part in content or []:
            if part.get("type") == "text":
                parts.append({"type": "input_text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": ensure_data_url(part.get("url", "")),
                        "detail": part.get("detail", image_detail),
                    }
                )
        input_items.append({"role": message["role"], "content": parts})
    return input_items


def map_responses_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    if not usage:
        return None
    return {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "prompt_tokens_details": usage.get("input_tokens_details"),
        "completion_tokens_details": usage.get("output_tokens_details"),
    }


def parse_response(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if status != "completed":
        error = (payload.get("error") or {}).get("message")
        incomplete = (payload.get("incomplete_details") or {}).get("reason")
        raise RuntimeError(
            f"Responses request {status}: "
            f"{error or incomplete or 'response did not complete'}"
        )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    content_parts.append(part.get("text", ""))
        elif item.get("type") == "reasoning":
            parts = item.get("content") or item.get("summary") or []
            for part in parts:
                text = part.get("text")
                if isinstance(text, str):
                    reasoning_parts.append(text)
    return {
        "content": "".join(content_parts),
        "reasoningContent": "".join(reasoning_parts),
        "rawAssistantOutput": {
            "type": "responses",
            "rawValue": payload.get("output"),
        },
        "rawUsage": map_responses_usage(payload.get("usage")),
        "responseModelName": payload.get("model"),
    }


# Backwards-compatible alias for the pre-split helper name.
_parse_responses_payload = parse_response
