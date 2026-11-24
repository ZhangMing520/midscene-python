"""Non-streaming Responses parsing (upstream responses/non-stream.ts)."""

from typing import Any

from midscene.core.ai_model.service_caller.openai.responses.utils import parse_response
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.utils import has_usable_text


def call_responses_non_streaming(payload: dict[str, Any]) -> dict[str, Any]:
    result = parse_response(payload)
    if not has_usable_text(result["content"]):
        raise AIResponseParseError(
            "empty content from AI model",
            result["content"],
            None,
            result["rawAssistantOutput"],
        )
    return {**result, "requestId": payload.get("id")}
