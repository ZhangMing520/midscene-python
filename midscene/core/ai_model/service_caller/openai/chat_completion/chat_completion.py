"""Chat-completion request preparation (upstream chat-completion/chat-completion.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_semantic_retry_temperature,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.openai.chat_completion.non_stream import (
    call_chat_completion_non_streaming,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.stream import (
    call_chat_completion_stream,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.utils import (
    to_chat_messages,
)
from midscene.core.ai_model.service_caller.utils import resolve_image_detail


async def call_chat_completion(options: dict[str, Any], stream: bool) -> dict[str, Any]:
    """Dispatch to the stream/non-stream parser (upstream callChatCompletion).

    Python's transport consumes the request before parsing, so ``options``
    carries either the decoded ``payload`` or the SSE ``lines`` plus ``adapter``.
    """
    if stream:
        return await call_chat_completion_stream(
            options["lines"],
            options["adapter"],
            options.get("onChunk") or options.get("on_chunk"),
        )
    return call_chat_completion_non_streaming(options["payload"], options["adapter"])


def _adapter_user_config(model_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "temperature": model_config.get("temperature"),
        "reasoningEnabled": model_config.get("reasoningEnabled"),
        "reasoningEffort": model_config.get("reasoningEffort"),
        "reasoningBudget": model_config.get("reasoningBudget"),
        "responseFormat": model_config.get("responseFormat"),
        "baseURL": model_config.get("openaiBaseURL"),
        "intent": model_config.get("intent"),
    }


def _strip_undefined(config: dict[str, Any]) -> dict[str, Any]:
    """Adapter builders may set a key to None to mean 'omit the parameter'."""
    return {key: value for key, value in config.items() if value is not None}


def prepare_chat_completion(
    messages: list[dict],
    model_runtime: ModelRuntime,
    options: dict[str, Any],
) -> dict[str, Any]:
    model_config = model_runtime.config
    adapter = model_runtime.adapter
    image_detail = resolve_image_detail(
        "high",
        model_config.get("intent"),
        bool(options.get("requiresOriginalImageDetail")),
    )
    midscene_defaults = {"temperature": 0.0}
    adapter_params = adapter.build_chat_completion_params(
        midscene_defaults,
        _adapter_user_config(model_config),
        bool(options.get("expectedJsonObjectResponse")),
    )
    if model_config.get("temperature") == "unset":
        adapter_params.pop("temperature", None)
    request_body: dict[str, Any] = {
        "model": model_config.get("modelName"),
        "messages": to_chat_messages(messages, image_detail),
        **_strip_undefined(adapter_params),
        **(model_config.get("extraBody") or {}),
    }
    _apply_semantic_retry_temperature(request_body, model_config, options)
    return {"request_body": request_body}
