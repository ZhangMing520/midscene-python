"""Gemini adapter (upstream ai-model/models/gemini.ts)."""

import re
from typing import Any, Dict, Optional

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)
from midscene.core.ai_model.models.default import (
    build_chat_completion_params_from_context,
)


def _build_gemini_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    _apply_temperature(config, user_config)
    reasoning_enabled = user_config.get("reasoningEnabled")
    if reasoning_enabled != "default":
        # Google's native thinking_config; relays reject the minimal level.
        config["extra_body"] = {
            "google": {
                "thinking_config": {
                    "include_thoughts": True,
                    "thinking_level": (
                        user_config.get("reasoningEffort") or "medium"
                    )
                    if reasoning_enabled
                    else "low",
                }
            }
        }
    return config


def _extract_inline_thought(content: str) -> Optional[str]:
    match = re.match(r"^<thought>([\s\S]*?)</thought>", content, re.IGNORECASE)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _format_reasoning_content(
    gemini_reasoning_content: str, provider_reasoning_content: str
) -> str:
    if gemini_reasoning_content and provider_reasoning_content:
        return (
            f"inlineThought：{gemini_reasoning_content}; "
            f"reasoning_content：{provider_reasoning_content}"
        )
    return gemini_reasoning_content or provider_reasoning_content or ""


def extract_gemini_content_and_reasoning(
    message: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Extract Gemini content plus inline/provider reasoning.

    Live tests with ``include_thoughts`` showed Google's endpoint prepending
    summaries as ``<thought>...</thought>`` in content. Extract the prefix
    without changing content.
    """
    if not message:
        return {"content": "", "reasoning_content": ""}

    content = message.get("content") if isinstance(message.get("content"), str) else ""
    gemini_reasoning_content = _extract_inline_thought(content) or ""
    provider_reasoning_content = (
        message.get("reasoning_content")
        if isinstance(message.get("reasoning_content"), str)
        else ""
    )

    return {
        "content": content,
        "reasoning_content": _format_reasoning_content(
            gemini_reasoning_content, provider_reasoning_content
        ),
    }


GEMINI_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {"shape": "bbox", "order": "yx", "normalizedBy": 1000, "rounding": "round"},
}


gemini_adapters = {
    "gemini": {
        "chat_completion": {
            "build_chat_completion_params": build_chat_completion_params_from_context(
                _build_gemini_params
            ),
            "message_extraction": {
                "kind": "custom",
                "extract_content_and_reasoning": extract_gemini_content_and_reasoning,
            },
        },
        "locate": {
            "element": {
                "result_format": GEMINI_LOCATE_FORMAT,
            },
        },
    },
}


__all__ = [
    "GEMINI_LOCATE_FORMAT",
    "_build_gemini_params",
    "extract_gemini_content_and_reasoning",
    "gemini_adapters",
]
