"""Chat-completion message helpers (upstream chat-completion/utils.ts)."""

from typing import Any, cast

from loguru import logger

from midscene.core.ai_model.service_caller.utils import has_usable_text


def ensure_data_url(url: str) -> str:
    if url.startswith(("data:", "http://", "https://")):
        return url
    return f"data:image/jpeg;base64,{url}"


def resolve_content_with_reasoning_fallback(
    content: str | None,
    reasoning_content: str,
    use_reasoning_as_content_fallback: bool,
) -> str | None:
    if (
        not has_usable_text(content)
        and use_reasoning_as_content_fallback
        and has_usable_text(reasoning_content)
    ):
        logger.warning("empty content from AI model, using reasoning content")
        return reasoning_content
    return content


def to_chat_messages(messages: list[dict], image_detail: str) -> list[dict]:
    """Convert internal messages to OpenAI chat-completion wire format.

    Conversation-history entries (``input-message`` / ``model-output``) are
    flattened to ordinary messages first, matching upstream ``toChatMessages``.
    """
    wire_messages: list[dict] = []
    for entry in messages:
        if entry.get("type") == "model-output" and "output" in entry:
            output = entry.get("output") or {}
            if output.get("type") != "chat-completion":
                raise ValueError(
                    "Cannot replay Responses output in a Chat Completions conversation"
                )
            wire_messages.append(cast(dict[str, Any], output.get("rawValue")))
            continue
        message = entry["message"] if entry.get("type") == "input-message" else entry
        raw_assistant = message.get("raw_assistant_message")
        if isinstance(raw_assistant, dict):
            # Kimi K3 requires replaying the complete assistant message
            # (reasoning_content / tool_calls) across turns.
            wire_messages.append({**raw_assistant, "role": "assistant"})
            continue
        content = message.get("content")
        if isinstance(content, str):
            wire_messages.append({"role": message["role"], "content": content})
            continue
        parts: list[dict] = []
        for part in content or []:
            if part.get("type") == "text":
                parts.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": ensure_data_url(part.get("url", "")),
                            "detail": part.get("detail", image_detail),
                        },
                    }
                )
            else:
                parts.append(part)
        wire_messages.append({"role": message["role"], "content": parts})
    return wire_messages
