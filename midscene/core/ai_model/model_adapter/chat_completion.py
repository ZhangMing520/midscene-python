"""Chat-completion request helpers (upstream ai-model/model-adapter/chat-completion.ts)."""

from typing import Any, Callable, Dict, List, Optional

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    get_temperature_with_semantic_retry,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

MIDSCENE_DEFAULT_TEMPERATURE = 0.0

MIDSCENE_CHAT_COMPLETION_DEFAULTS: Dict[str, Any] = {"temperature": 0}


def _json_object_config(
    user_config: ModelRequestUserConfig, expected_json_object_response: bool
) -> Dict[str, Any]:
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        return {"response_format": {"type": "json_object"}}
    return {}


def _default_chat_completion_params(context: Dict[str, Any]) -> Dict[str, Any]:
    user_config = context.get("userConfig") or {}
    defaults = context.get("midsceneDefaults") or MIDSCENE_CHAT_COMPLETION_DEFAULTS
    return {"config": {"temperature": user_config.get("temperature", defaults.get("temperature"))}}


def _create_default_extract_content_and_reasoning(
    reasoning_content_keys: List[str],
) -> Callable[[Optional[Dict[str, Any]]], Dict[str, str]]:
    """Port of upstream createDefaultExtractContentAndReasoning."""

    def extract(message: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if not message:
            return {"content": "", "reasoning_content": ""}
        raw_reasoning = next(
            (
                message.get(key)
                for key in reasoning_content_keys
                if isinstance(message.get(key), str)
            ),
            "",
        )
        return {
            "content": (
                message.get("content")
                if isinstance(message.get("content"), str)
                else ""
            ),
            "reasoning_content": (
                raw_reasoning if isinstance(raw_reasoning, str) else ""
            ),
        }

    return extract


def _resolve_extract_content_and_reasoning(
    chat_completion: Optional[Dict[str, Any]],
) -> Callable[[Optional[Dict[str, Any]]], Dict[str, str]]:
    chat_completion = chat_completion or {}
    message_extraction = chat_completion.get("message_extraction") or {}
    if message_extraction.get("kind") == "custom":
        return message_extraction["extract_content_and_reasoning"]
    return _create_default_extract_content_and_reasoning(
        message_extraction.get("reasoning_content_keys") or ["reasoning_content"]
    )


def resolve_chat_completion(
    chat_completion: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve a chat-completion definition into a runtime adapter.

    Mirrors upstream ``resolveChatCompletion``: the returned mapping exposes
    ``build_chat_completion_params``, ``extract_content_and_reasoning``,
    ``use_reasoning_as_content_fallback`` and ``replay_raw_assistant_message``.
    """
    chat_completion = chat_completion or {}
    build_params = (
        chat_completion.get("build_chat_completion_params")
        or _default_chat_completion_params
    )
    extract_content_and_reasoning = _resolve_extract_content_and_reasoning(
        chat_completion
    )
    use_reasoning_as_content_fallback = bool(
        chat_completion.get("use_reasoning_as_content_fallback", False)
    )
    replay_raw_assistant_message = bool(
        chat_completion.get("replay_raw_assistant_message", False)
    )

    def build_chat_completion_params(input_context: Dict[str, Any]) -> Dict[str, Any]:
        context = {
            **input_context,
            "userConfig": input_context.get("userConfig") or {},
            "midsceneDefaults": MIDSCENE_CHAT_COMPLETION_DEFAULTS,
        }
        params = build_params(context)
        return {
            **params,
            "config": {
                **(params.get("config") or {}),
                "temperature": get_temperature_with_semantic_retry(
                    (params.get("config") or {}).get("temperature"),
                    (input_context.get("userConfig") or {}).get("temperature"),
                    input_context.get("semanticRetryAttempt") or 0,
                ),
            },
        }

    return {
        "build_chat_completion_params": build_chat_completion_params,
        "extract_content_and_reasoning": extract_content_and_reasoning,
        "use_reasoning_as_content_fallback": use_reasoning_as_content_fallback,
        "replay_raw_assistant_message": replay_raw_assistant_message,
    }


__all__ = [
    "MIDSCENE_CHAT_COMPLETION_DEFAULTS",
    "MIDSCENE_DEFAULT_TEMPERATURE",
    "_json_object_config",
    "resolve_chat_completion",
]
