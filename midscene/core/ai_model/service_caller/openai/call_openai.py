"""OpenAI protocol dispatch (upstream openai/call-openai.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.service_caller.openai.chat_completion.non_stream import (
    call_chat_completion_non_streaming,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.stream import (
    call_chat_completion_stream,
)
from midscene.core.ai_model.service_caller.openai.openai_client import (
    post_json,
    request_headers,
    resolve_endpoint,
    resolve_proxy,
    stream_lines,
)
from midscene.core.ai_model.service_caller.openai.responses.non_stream import (
    call_responses_non_streaming,
)
from midscene.core.ai_model.service_caller.openai.responses.stream import (
    call_responses_stream,
)


async def call_openai(
    model_runtime: Any,
    protocol: str,
    prepared: Dict[str, Any],
    stream: bool,
    on_chunk: Optional[Any] = None,
    effective_timeout: Optional[float] = None,
    execution_id: Optional[str] = None,
    record_event: Optional[Any] = None,
) -> Dict[str, Any]:
    """Send a prepared request and return the parsed model result."""
    model_config = model_runtime.config
    url = resolve_endpoint(model_config, protocol)
    headers = request_headers(model_config, execution_id)
    proxy = resolve_proxy(model_config)
    request_body = prepared["request_body"]

    if protocol == "openai-responses":
        if stream:
            parsed = await call_responses_stream(
                stream_lines(
                    url,
                    headers,
                    request_body,
                    effective_timeout,
                    proxy,
                    record_event=record_event,
                ),
                on_chunk,
            )
        else:
            payload = await post_json(
                url,
                headers,
                request_body,
                effective_timeout,
                proxy,
                record_event=record_event,
            )
            parsed = call_responses_non_streaming(payload)
    elif stream:
        stream_body = {
            **request_body,
            "stream_options": {
                **(request_body.get("stream_options") or {}),
                "include_usage": True,
            },
        }
        parsed = await call_chat_completion_stream(
            stream_lines(
                url,
                headers,
                stream_body,
                effective_timeout,
                proxy,
                record_event=record_event,
            ),
            model_runtime.adapter,
            on_chunk,
        )
    else:
        payload = await post_json(
            url,
            headers,
            request_body,
            effective_timeout,
            proxy,
            record_event=record_event,
        )
        parsed = call_chat_completion_non_streaming(payload, model_runtime.adapter)

    if record_event:
        record_event(
            {
                "type": "response",
                "final": {
                    "content": parsed.get("content"),
                    "reasoningContent": parsed.get("reasoningContent"),
                    "usage": parsed.get("rawUsage"),
                    "requestId": parsed.get("requestId"),
                    "responseModelName": parsed.get("responseModelName"),
                },
            }
        )
    return parsed
