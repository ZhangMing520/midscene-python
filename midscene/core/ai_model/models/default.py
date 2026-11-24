"""Default model parameters and locate format (upstream ai-model/models/default.ts)."""

from collections.abc import Callable
from typing import Any

from midscene.core.ai_model.model_adapter.chat_completion import (
    MIDSCENE_CHAT_COMPLETION_DEFAULTS,
)
from midscene.core.ai_model.model_adapter.responses import (
    MIDSCENE_RESPONSES_DEFAULTS,
)
from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)


def _build_default_params(
    midscene_defaults: dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(midscene_defaults)
    return _apply_temperature(config, user_config)


def build_chat_completion_params_from_context(
    builder: Callable[..., dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Adapt a Python ``(defaults, user_config, expected)`` builder to the
    context-object signature used by upstream adapter definitions."""

    def build(input_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = input_context or {}
        user_config = dict(context.get("userConfig") or {})
        if context.get("baseURL") is not None and "baseURL" not in user_config:
            user_config["baseURL"] = context["baseURL"]
        config = builder(
            context.get("midsceneDefaults") or MIDSCENE_CHAT_COMPLETION_DEFAULTS,
            user_config,
            bool(context.get("expectedJsonObjectResponse")),
        )
        return {"config": config}

    return build


def build_responses_params_from_context(
    builder: Callable[..., dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Adapt a Python Responses builder to the upstream context-object signature."""

    def build(input_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = input_context or {}
        config = builder(
            context.get("midsceneDefaults") or MIDSCENE_RESPONSES_DEFAULTS,
            context.get("userConfig") or {},
            bool(context.get("expectedJsonObjectResponse")),
        )
        return {"config": config}

    return build


DEFAULT_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {
        "shape": "bbox",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    },
}


default_open_ai_compatible_adapter_config: dict[str, Any] = {
    "chat_completion": {
        # Many OpenAI-compatible servers expose useful assistant output through
        # reasoning_content, so the default adapter recovers when content is empty.
        "use_reasoning_as_content_fallback": True,
    },
}


__all__ = [
    "DEFAULT_LOCATE_FORMAT",
    "_build_default_params",
    "build_chat_completion_params_from_context",
    "build_responses_params_from_context",
    "default_open_ai_compatible_adapter_config",
]
