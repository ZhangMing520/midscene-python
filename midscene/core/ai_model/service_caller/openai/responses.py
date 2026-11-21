"""OpenAI responses request body (upstream service-caller/openai/responses)."""

from typing import Any, Dict, List

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_semantic_retry_temperature,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.openai.chat_completion import (
    _adapter_user_config,
    _strip_undefined,
)
from midscene.core.ai_model.service_caller.utils import (
    map_responses_usage,
    resolve_image_detail,
    to_responses_input,
)


def prepare_responses(
    messages: List[dict],
    model_runtime: ModelRuntime,
    options: Dict[str, Any],
) -> Dict[str, Any]:
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
    adapter_params = (
        builder(midscene_defaults, user_config, bool(options.get("expectedJsonObjectResponse")))
        if builder
        else {**midscene_defaults, **{
            key: value
            for key, value in user_config.items()
            if value is not None and value != "unset"
        }}
    )
    if model_config.get("temperature") == "unset":
        adapter_params.pop("temperature", None)
    request_body: Dict[str, Any] = {
        "store": False,
        **_strip_undefined(adapter_params),
        **(model_config.get("extraBody") or {}),
        "model": model_config.get("modelName"),
        "input": to_responses_input(messages, image_detail),
    }
    if request_body.get("background") is True:
        raise ValueError("Responses background mode is not supported")
    _apply_semantic_retry_temperature(request_body, model_config, options)
    return {"request_body": request_body}


def _parse_responses_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    status = payload.get("status")
    if status != "completed":
        error = (payload.get("error") or {}).get("message")
        incomplete = (payload.get("incomplete_details") or {}).get("reason")
        raise RuntimeError(
            f"Responses request {status}: {error or incomplete or 'response did not complete'}"
        )
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
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
        "rawAssistantOutput": {"type": "responses", "rawValue": payload.get("output")},
        "rawUsage": map_responses_usage(payload.get("usage")),
        "responseModelName": payload.get("model"),
    }
