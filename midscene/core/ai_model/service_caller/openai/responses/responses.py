"""Responses request preparation (upstream responses/responses.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_semantic_retry_temperature,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.openai.chat_completion.chat_completion import (
    _adapter_user_config,
    _strip_undefined,
)
from midscene.core.ai_model.service_caller.openai.responses.non_stream import (
    call_responses_non_streaming,
)
from midscene.core.ai_model.service_caller.openai.responses.stream import (
    call_responses_stream,
)
from midscene.core.ai_model.service_caller.openai.responses.utils import (
    to_responses_input,
)
from midscene.core.ai_model.service_caller.utils import resolve_image_detail


async def call_responses(options: dict[str, Any], stream: bool) -> dict[str, Any]:
    """Dispatch to the stream/non-stream parser (upstream callResponses)."""
    if stream:
        return await call_responses_stream(
            options["lines"],
            options.get("onChunk") or options.get("on_chunk"),
        )
    return call_responses_non_streaming(options["payload"])


def prepare_responses(
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
    user_config = _adapter_user_config(model_config)
    if "temperature" in adapter.unsupported_user_config:
        user_config.pop("temperature", None)
    builder = getattr(adapter, "build_responses_params", None)
    if builder:
        adapter_params = builder(
            midscene_defaults,
            user_config,
            bool(options.get("expectedJsonObjectResponse")),
        )
    else:
        from midscene.core.ai_model.model_adapter.responses import (
            build_default_responses_params,
        )

        adapter_params = build_default_responses_params(midscene_defaults, user_config)
    if model_config.get("temperature") == "unset":
        adapter_params.pop("temperature", None)
    request_body: dict[str, Any] = {
        "store": False,
        **_strip_undefined(adapter_params),
        **(model_config.get("extraBody") or {}),
        "model": model_config.get("modelName"),
        "input": to_responses_input(messages, image_detail),
    }
    if model_config.get("authMode") == "siwc":
        # SIWC does not support temperature, including explicit user overrides.
        request_body.pop("temperature", None)
    if request_body.get("background") is True:
        raise ValueError("Responses background mode is not supported")
    _apply_semantic_retry_temperature(request_body, model_config, options)
    return {"request_body": request_body}
