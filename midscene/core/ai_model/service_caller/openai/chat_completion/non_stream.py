"""Non-streaming chat-completion parsing (upstream chat-completion/non-stream.ts)."""

from typing import Any, Dict
import json

from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.utils import (
    extract_content_and_reasoning,
    has_usable_text,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.utils import (
    resolve_content_with_reasoning_fallback,
)


def call_chat_completion_non_streaming(
    payload: Dict[str, Any],
    adapter: Any,
) -> Dict[str, Any]:
    if not payload.get("choices"):
        raise RuntimeError(
            f"invalid response from LLM service: {json.dumps(payload)[:2000]}"
        )
    raw_message = payload["choices"][0].get("message") or {}
    parsed_message = extract_content_and_reasoning(
        raw_message, adapter.reasoning_content_keys
    )
    reasoning_content = parsed_message["reasoning_content"]
    content = resolve_content_with_reasoning_fallback(
        parsed_message["content"],
        reasoning_content,
        adapter.use_reasoning_as_content_fallback,
    )
    raw_assistant_output = {
        "type": "chat-completion",
        "rawValue": raw_message,
    }
    if not has_usable_text(content):
        raise AIResponseParseError(
            "empty content from AI model",
            content or "",
            payload.get("usage"),
            raw_assistant_output,
        )
    return {
        "content": content,
        "reasoningContent": reasoning_content,
        "rawAssistantOutput": raw_assistant_output,
        "rawUsage": payload.get("usage"),
        "requestId": payload.get("id"),
        "responseModelName": payload.get("model"),
    }
