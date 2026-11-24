"""OpenAI protocol dispatch (upstream openai/call-openai.ts)."""

from typing import Any

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


async def call_open_ai(
    context: dict[str, Any],
    prepared: dict[str, Any],
) -> dict[str, Any]:
    """Upstream-shaped entry point over the shared OpenAI transport.

    ``context`` carries the model runtime, call options, execution id and
    recording callback; ``prepared`` is a ``{kind, input}`` dispatch record.
    """
    model_runtime = _context_value(context, "modelRuntime", "model_runtime")
    options = _context_value(context, "options") or {}
    abort_signal = _context_value(context, "requestSignal", "request_signal")
    if abort_signal is not None:
        abort_signal.throw_if_aborted()

    kind = prepared.get("kind")
    input_data = prepared.get("input") or prepared
    if "request_body" not in input_data and "requestParams" in input_data:
        input_data = {**input_data, "request_body": input_data["requestParams"]}

    protocol = "openai-responses" if kind == "responses" else "openai-chat"
    if "stream" in options:
        stream = options["stream"] is True
    else:
        stream = model_runtime.config.get("streamMode") == "stream"
    on_chunk = options.get("onChunk") or options.get("on_chunk")

    return await call_openai(
        model_runtime,
        protocol,
        input_data,
        stream,
        on_chunk=on_chunk,
        effective_timeout=_context_value(
            context, "effectiveTimeoutMs", "effective_timeout_ms"
        ),
        execution_id=_context_value(context, "executionId", "execution_id"),
        record_event=_context_value(context, "recordEvent", "record_event"),
    )


def _context_value(context: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in context:
            return context[key]
    return default


async def call_openai(
    model_runtime: Any,
    protocol: str,
    prepared: dict[str, Any],
    stream: bool,
    on_chunk: Any | None = None,
    effective_timeout: float | None = None,
    execution_id: str | None = None,
    record_event: Any | None = None,
) -> dict[str, Any]:
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
