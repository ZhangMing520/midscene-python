"""Generative AI service caller (OpenAI chat-completion + responses protocols).

Synced from upstream web-infra-dev/midscene v1.17.4:
  packages/core/src/ai-model/service-caller/call-ai.ts        (retry loop, SIWC)
  packages/core/src/ai-model/service-caller/request-timeout.ts
  packages/core/src/ai-model/service-caller/openai/chat-completion/*  (incl. stream)
  packages/core/src/ai-model/service-caller/openai/responses/*        (incl. stream)
  packages/core/src/ai-model/service-caller/utils.ts          (usage building)

The Codex app-server transport (baseURL `codex://...`) requires the Codex
binary over stdio JSON-RPC and is not supported by the Python SDK; it raises
a clear error.
"""

import asyncio
import inspect
import json
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from .adapters import ModelRuntime, is_locate_intent
from .siwc import (
    SiwcTokenExpiredError,
    prepare_siwc_call,
    siwc_token_manager,
)


class AIResponseParseError(Exception):
    """Error that preserves usage and raw response when AI parsing fails."""

    def __init__(
        self,
        message: str,
        raw_response: str,
        usage: Optional[Dict[str, Any]] = None,
        raw_assistant_output: Optional[Dict[str, Any]] = None,
        reasoning_content: Optional[str] = None,
    ):
        super().__init__(message)
        self.raw_response = raw_response
        self.usage = usage
        self.raw_assistant_output = raw_assistant_output
        self.reasoning_content = reasoning_content


class CodexAppServerNotSupportedError(NotImplementedError):
    pass


def has_usable_text(content: Optional[str]) -> bool:
    return bool(content) and content.strip() != ""


def normalize_retry_count(retry_count: Any) -> int:
    if not isinstance(retry_count, (int, float)) or retry_count != retry_count:
        return 1
    return max(0, int(retry_count))


def next_internal_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


CODEX_PROVIDER_SCHEME = "codex://"


def is_codex_app_server_provider(base_url: Optional[str]) -> bool:
    if not base_url:
        return False
    return base_url.strip().lower().startswith(CODEX_PROVIDER_SCHEME)


# ---------------------------------------------------------------------------
# Message conversion (internal normalized -> OpenAI wire format)
# ---------------------------------------------------------------------------

def _ensure_data_url(url: str) -> str:
    if url.startswith(("data:", "http://", "https://")):
        return url
    return f"data:image/jpeg;base64,{url}"


def to_chat_messages(messages: List[dict], image_detail: str) -> List[dict]:
    """Convert internal messages to OpenAI chat-completion wire format."""
    wire_messages: List[dict] = []
    for message in messages:
        raw_assistant = message.get("raw_assistant_message")
        if isinstance(raw_assistant, dict):
            # Kimi K3 requires replaying the complete assistant message
            # (reasoning_content / tool_calls) across turns.
            wire_messages.append({**raw_assistant, "role": "assistant"})
            continue
        content = message.get("content")
        if isinstance(content, str):
            wire_messages.append({"role": message["role"], "content": content})
            continue
        parts: List[dict] = []
        for part in content or []:
            if part.get("type") == "text":
                parts.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _ensure_data_url(part.get("url", "")),
                            "detail": part.get("detail", image_detail),
                        },
                    }
                )
            else:
                parts.append(part)
        wire_messages.append({"role": message["role"], "content": parts})
    return wire_messages


def to_responses_input(messages: List[dict], image_detail: str) -> List[dict]:
    """Convert internal messages to the Responses API input format."""
    input_items: List[dict] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            input_items.append({"role": message["role"], "content": content})
            continue
        if message["role"] == "assistant":
            text = "".join(part.get("text", "") for part in content or [])
            input_items.append({"role": "assistant", "content": text})
            continue
        parts: List[dict] = []
        for part in content or []:
            if part.get("type") == "text":
                parts.append({"type": "input_text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": _ensure_data_url(part.get("url", "")),
                        "detail": part.get("detail", image_detail),
                    }
                )
        input_items.append({"role": message["role"], "content": parts})
    return input_items


def resolve_image_detail(
    adapter_detail: str, intent: Optional[str], requires_original: bool
) -> str:
    if requires_original or is_locate_intent(intent):
        return "high"  # 'original' is not portable across OpenAI-compatible servers
    return adapter_detail or "high"


def extract_content_and_reasoning(
    message: Optional[Dict[str, Any]], reasoning_keys: List[str]
) -> Dict[str, str]:
    content = ""
    reasoning = ""
    if message:
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            content = "".join(
                part.get("text", "")
                for part in raw_content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        for key in reasoning_keys:
            value = message.get(key)
            if isinstance(value, str) and value:
                reasoning = value
                break
            if isinstance(value, list):
                joined = "".join(
                    part.get("text", "")
                    for part in value
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                if joined:
                    reasoning = joined
                    break
    return {"content": content, "reasoning_content": reasoning}


# ---------------------------------------------------------------------------
# Usage building (utils.ts buildUsageInfo)
# ---------------------------------------------------------------------------

def map_responses_usage(usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not usage:
        return None
    return {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "prompt_tokens_details": usage.get("input_tokens_details"),
        "completion_tokens_details": usage.get("output_tokens_details"),
    }


def build_usage_info(
    raw_usage: Optional[Dict[str, Any]],
    model_config: Dict[str, Any],
    time_cost: Optional[int],
    retry_count: int,
    request_id: Optional[str],
    response_model_name: Optional[str],
    internal_call_id: str,
) -> Optional[Dict[str, Any]]:
    if not raw_usage:
        return None

    def _num(key: str) -> int:
        value = raw_usage.get(key)
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

    prompt_tokens = _num("prompt_tokens")
    completion_tokens = _num("completion_tokens")
    details = raw_usage.get("prompt_tokens_details") or {}
    try:
        cached_input = int(details.get("cached_tokens") or 0)
    except (TypeError, ValueError):
        cached_input = 0
    total_tokens = _num("total_tokens") or (prompt_tokens + completion_tokens)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_input": cached_input,
        "time_cost": time_cost,
        "retry": retry_count,
        "request_id": request_id,
        "model_name": response_model_name or model_config.get("modelName"),
        "model_description": model_config.get("modelDescription", ""),
        "model_family": model_config.get("modelFamily"),
        "intent": model_config.get("intent"),
        "slot": model_config.get("slot"),
        "_midscene_call_id": internal_call_id,
    }


def resolve_effective_timeout_ms(timeout: Optional[float]) -> Optional[float]:
    """Per-request hard timeout in milliseconds. None disables the Midscene timeout."""
    if timeout is None:
        return 180_000.0
    if timeout <= 0:
        return None
    return float(timeout)


DEFAULT_MODEL_PROTOCOL = "openai-chat"


# ---------------------------------------------------------------------------
# Request preparation
# ---------------------------------------------------------------------------

def _adapter_user_config(model_config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "temperature": model_config.get("temperature"),
        "reasoningEnabled": model_config.get("reasoningEnabled"),
        "reasoningEffort": model_config.get("reasoningEffort"),
        "reasoningBudget": model_config.get("reasoningBudget"),
        "responseFormat": model_config.get("responseFormat"),
    }


def _strip_undefined(config: Dict[str, Any]) -> Dict[str, Any]:
    """Adapter builders may set a key to None to mean 'omit the parameter'."""
    return {key: value for key, value in config.items() if value is not None}


def prepare_chat_completion(
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
    adapter_params = adapter.build_chat_completion_params(
        midscene_defaults,
        _adapter_user_config(model_config),
        bool(options.get("expectedJsonObjectResponse")),
    )
    request_body: Dict[str, Any] = {
        "model": model_config.get("modelName"),
        "messages": to_chat_messages(messages, image_detail),
        **_strip_undefined(adapter_params),
        **(model_config.get("extraBody") or {}),
    }
    _apply_semantic_retry_temperature(request_body, model_config, options)
    return {"request_body": request_body}


def _apply_semantic_retry_temperature(
    request_body: Dict[str, Any],
    model_config: Dict[str, Any],
    options: Dict[str, Any],
) -> None:
    """Nudge the deterministic default temperature after a parse failure."""
    attempt = options.get("semanticRetryAttempt") or 0
    if (
        attempt > 0
        and model_config.get("temperature") is None
        and request_body.get("temperature") == 0
    ):
        request_body["temperature"] = 0.2


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
            key: value for key, value in user_config.items() if value is not None
        }}
    )
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


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------

def _request_headers(model_config: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = model_config.get("openaiApiKey")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    extra_config = model_config.get("openaiExtraConfig") or {}
    extra_headers = (
        extra_config.get("defaultHeaders")
        or extra_config.get("extraHeaders")
        or extra_config.get("extra_headers")
    )
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    return headers


def _is_siwc_token_expired(status_code: int, body: str) -> bool:
    if status_code != 401:
        return False
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    return isinstance(error, dict) and error.get("code") == "token_expired"


def _raise_http_error(status_code: int, body: str) -> None:
    if _is_siwc_token_expired(status_code, body):
        raise SiwcTokenExpiredError(body[:2000])
    raise RuntimeError(
        f"LLM service response error, status: {status_code}, body: {body[:2000]}"
    )


async def _post_json(
    url: str,
    headers: Dict[str, str],
    request_body: Dict[str, Any],
    effective_timeout: Optional[float],
    proxy: Optional[str],
    stream: bool,
    on_chunk: Optional[Any] = None,
):
    timeout_seconds = (
        effective_timeout / 1000 if effective_timeout is not None else None
    )
    timeout = httpx.Timeout(timeout_seconds) if timeout_seconds else None
    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            if stream:
                request_body = {**request_body, "stream": True}
                async with client.stream(
                    "POST", url, headers=headers, json=request_body
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")
                        _raise_http_error(response.status_code, body)
                    return await _aggregate_stream_lines(
                        response.aiter_lines(), on_chunk
                    )
            response = await client.post(url, headers=headers, json=request_body)
    except httpx.TimeoutException as e:
        raise RuntimeError(
            f"model request timeout after {effective_timeout}ms"
        ) from e

    if response.status_code >= 400:
        _raise_http_error(response.status_code, response.text)
    try:
        return response.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid JSON response from LLM service: {e}") from e


async def _emit_stream_chunk(
    on_chunk: Optional[Any],
    content: str,
    reasoning_content: str,
    accumulated: str,
    is_complete: bool = False,
    usage: Optional[Dict[str, Any]] = None,
) -> None:
    """Deliver a CodeGenerationChunk to the caller (upstream onChunk)."""
    if on_chunk is None:
        return
    chunk = {
        "content": content,
        "reasoning_content": reasoning_content,
        "accumulated": accumulated,
        "isComplete": is_complete,
        "usage": usage,
    }
    result = on_chunk(chunk)
    if inspect.isawaitable(result):
        await result


async def _aggregate_stream_lines(
    lines, on_chunk: Optional[Any] = None
) -> Dict[str, Any]:
    """Aggregate an SSE stream (chat-completion or responses) into a full
    payload, then reuse the non-stream parsers."""
    is_responses = False
    completed = False
    completed_output: Optional[List[Dict[str, Any]]] = None
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    accumulated = ""
    accumulated_reasoning = ""
    usage: Optional[Dict[str, Any]] = None
    response_model: Optional[str] = None
    response_id: Optional[str] = None
    responses_output: List[Dict[str, Any]] = []

    async for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type") or ""
        if event_type == "error":
            error = event.get("error") or event.get("message")
            raise RuntimeError(f"Responses stream error: {error}")
        if event_type in ("response.failed", "response.incomplete"):
            response = event.get("response") or {}
            reason = (
                (response.get("error") or {}).get("message")
                or (response.get("incomplete_details") or {}).get("reason")
                or "response did not complete"
            )
            raise RuntimeError(f"Responses stream {event_type}: {reason}")
        if event_type == "response.completed":
            is_responses = True
            completed = True
            response = event.get("response") or {}
            response_model = response.get("model") or response_model
            response_id = response.get("id") or response_id
            if response.get("usage"):
                usage = response["usage"]
            if response.get("output"):
                completed_output = response["output"]
            continue
        if "response" in event and isinstance(event.get("response"), dict):
            is_responses = True
            response = event["response"]
            response_model = response.get("model") or response_model
            response_id = response.get("id") or response_id
            if response.get("usage"):
                usage = response["usage"]
            continue
        if event_type == "response.output_item.done":
            item = event.get("item")
            if item:
                responses_output.append(item)
            continue
        if event_type == "response.output_text.delta":
            piece = event.get("delta", "") or ""
            content_parts.append(piece)
            accumulated += piece
            await _emit_stream_chunk(on_chunk, piece, "", accumulated)
            continue
        if event_type == "response.reasoning_summary_text.delta":
            piece = event.get("delta", "") or ""
            reasoning_parts.append(piece)
            accumulated_reasoning += piece
            await _emit_stream_chunk(on_chunk, "", piece, accumulated)
            continue
        choices = event.get("choices")
        if not choices:
            if event.get("usage"):
                usage = event["usage"]
            if event.get("model"):
                response_model = event["model"]
            continue
        delta = choices[0].get("delta") or {}
        content_piece = ""
        piece = delta.get("content")
        if isinstance(piece, str):
            content_piece = piece
            content_parts.append(piece)
        elif isinstance(piece, list):
            content_piece = "".join(
                part.get("text", "")
                for part in piece
                if isinstance(part, dict) and part.get("type") == "text"
            )
            content_parts.extend(
                part.get("text", "")
                for part in piece
                if isinstance(part, dict) and part.get("type") == "text"
            )
        reasoning_piece = ""
        for key in ("reasoning_content", "reasoning"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                reasoning_piece += value
                reasoning_parts.append(value)
        if content_piece or reasoning_piece:
            accumulated += content_piece
            accumulated_reasoning += reasoning_piece
            await _emit_stream_chunk(
                on_chunk, content_piece, reasoning_piece, accumulated
            )
        if event.get("usage"):
            usage = event["usage"]
        if event.get("model"):
            response_model = event["model"]

    await _emit_stream_chunk(
        on_chunk, "", "", accumulated or "".join(content_parts), True, usage
    )

    if is_responses:
        if not completed:
            raise RuntimeError(
                "Responses stream ended without a response.completed event"
            )
        payload: Dict[str, Any] = {
            "status": "completed",
            "output": completed_output or responses_output,
            "usage": usage,
            "model": response_model,
            "id": response_id,
        }
        result = _parse_responses_payload(payload)
        return {**result, "is_responses": True}

    message = {
        "role": "assistant",
        "content": "".join(content_parts),
        "reasoning_content": "".join(reasoning_parts),
    }
    return {
        "content": message["content"],
        "reasoningContent": message["reasoning_content"],
        "rawAssistantOutput": {"type": "chat-completion", "rawValue": message},
        "rawUsage": usage,
        "requestId": None,
        "responseModelName": response_model,
        "is_responses": False,
    }


def _finalize_result(
    result: Dict[str, Any],
    adapter: Any,
    model_config: Dict[str, Any],
) -> Dict[str, Any]:
    content = result.get("content") or ""
    reasoning_content = result.get("reasoningContent") or ""
    if not has_usable_text(content) and adapter.use_reasoning_as_content_fallback:
        if has_usable_text(reasoning_content):
            logger.warning("empty content from AI model, using reasoning content")
            content = reasoning_content
    if not has_usable_text(content):
        raise AIResponseParseError(
            "empty content from AI model",
            content or "",
            result.get("rawUsage"),
            result.get("rawAssistantOutput"),
        )
    return {
        "content": content,
        "reasoningContent": reasoning_content,
        "rawAssistantOutput": result.get("rawAssistantOutput"),
        "rawUsage": result.get("rawUsage"),
        "requestId": result.get("requestId"),
        "responseModelName": result.get("responseModelName"),
    }


async def call_generative_ai(
    messages: List[dict],
    original_model_runtime: ModelRuntime,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call the model and return {content, reasoning_content, usage, ...}."""
    options = dict(options or {})
    model_runtime, siwc_options = await prepare_siwc_call(original_model_runtime)
    if siwc_options:
        options.update(siwc_options)

    model_config = model_runtime.config
    protocol = model_config.get("protocol") or DEFAULT_MODEL_PROTOCOL

    if is_codex_app_server_provider(model_config.get("openaiBaseURL")):
        raise CodexAppServerNotSupportedError(
            "The Codex app-server transport (baseURL codex://...) requires the "
            "Codex binary over stdio JSON-RPC and is not supported by the "
            "Python SDK. Use the OpenAI API instead."
        )
    if protocol == "openai-responses":
        if not model_runtime.adapter.supports_protocol("openai-responses"):
            raise ValueError(
                f'Model adapter "{model_config.get("modelFamily") or "default"}" '
                'does not support protocol "openai-responses"'
            )
    elif protocol != "openai-chat":
        raise ValueError(f"Unsupported model protocol: {protocol}")

    api_key = model_config.get("openaiApiKey")
    base_url = (
        model_config.get("openaiBaseURL") or "https://api.openai.com/v1"
    ).rstrip("/")
    url = (
        f"{base_url}/responses"
        if protocol == "openai-responses"
        else f"{base_url}/chat/completions"
    )
    proxy: Optional[str] = (
        model_config.get("httpProxy") or model_config.get("socksProxy") or None
    )
    headers = _request_headers(model_config)
    effective_timeout = resolve_effective_timeout_ms(model_config.get("timeout"))
    internal_call_id = next_internal_call_id()

    stream_requested = (
        options.get("stream") is True
        or model_config.get("streamMode") == "stream"
    )
    on_chunk = options.get("onChunk") or options.get("on_chunk")
    if options.get("stream") is True and on_chunk is None:
        raise RuntimeError(
            "onChunk is required when stream: true is explicitly specified"
        )
    chunk_delivered = False

    def _track_chunk(chunk: Dict[str, Any]) -> Any:
        nonlocal chunk_delivered
        chunk_delivered = True
        return on_chunk(chunk)

    chunk_callback = _track_chunk if on_chunk is not None else None

    if protocol == "openai-responses":
        prepared = prepare_responses(messages, model_runtime, options)
    else:
        prepared = prepare_chat_completion(messages, model_runtime, options)
    request_body = prepared["request_body"]
    if stream_requested and protocol != "openai-responses":
        request_body = {
            **request_body,
            "stream_options": {"include_usage": True},
        }

    max_attempts = normalize_retry_count(model_config.get("retryCount")) + 1
    retry_interval = model_config.get("retryInterval") or 2000
    attempt_errors: List[str] = []
    start_time = time.time()
    attempt = 0
    siwc_refreshed = False

    while attempt < max_attempts:
        attempt += 1
        try:
            payload = await _post_json(
                url=url,
                headers=headers,
                request_body=request_body,
                effective_timeout=effective_timeout,
                proxy=proxy,
                stream=stream_requested,
                on_chunk=chunk_callback,
            )
            if protocol == "openai-responses" and not isinstance(payload, dict):
                raise RuntimeError("invalid responses payload")
            if "is_responses" in payload:
                # aggregated stream result, already parsed
                parsed = payload
            elif protocol == "openai-responses":
                parsed = _parse_responses_payload(payload)
            else:
                if not payload.get("choices"):
                    raise RuntimeError(
                        f"invalid response from LLM service: {json.dumps(payload)[:2000]}"
                    )
                raw_message = payload["choices"][0].get("message") or {}
                parsed_message = extract_content_and_reasoning(
                    raw_message, model_runtime.adapter.reasoning_content_keys
                )
                parsed = {
                    "content": parsed_message["content"],
                    "reasoningContent": parsed_message["reasoning_content"],
                    "rawAssistantOutput": {
                        "type": "chat-completion",
                        "rawValue": raw_message,
                    },
                    "rawUsage": payload.get("usage"),
                    "requestId": payload.get("id"),
                    "responseModelName": payload.get("model"),
                }

            final = _finalize_result(parsed, model_runtime.adapter, model_config)
            time_cost = int((time.time() - start_time) * 1000)
            usage = build_usage_info(
                raw_usage=parsed.get("rawUsage"),
                model_config=model_config,
                time_cost=time_cost,
                retry_count=attempt - 1,
                request_id=parsed.get("requestId"),
                response_model_name=parsed.get("responseModelName"),
                internal_call_id=internal_call_id,
            )
            if usage and model_runtime.on_usage:
                model_runtime.on_usage(usage)
            return {
                **final,
                "usage": usage,
                "reasoning_content": final.get("reasoningContent"),
                "raw_assistant_output": final.get("rawAssistantOutput"),
            }
        except SiwcTokenExpiredError:
            # One authentication retry, independent of the normal retryCount.
            if siwc_refreshed:
                raise RuntimeError("SIWC token rejected after refresh")
            current_key = model_config.get("openaiApiKey") or api_key
            if not current_key:
                raise RuntimeError("Missing rejected SIWC access token")
            refreshed_key = await siwc_token_manager.refresh_access_token(
                current_key
            )
            siwc_refreshed = True
            headers["Authorization"] = f"Bearer {refreshed_key}"
            model_config = {**model_config, "openaiApiKey": refreshed_key}
            api_key = refreshed_key
            attempt -= 1
            continue
        except AIResponseParseError:
            # A structurally invalid/empty completion is retryable upstream.
            if chunk_delivered or attempt >= max_attempts:
                raise
            logger.warning(
                f"AI response parsing failed (attempt {attempt}/{max_attempts}), "
                f"retrying in {retry_interval}ms..."
            )
            await asyncio.sleep(retry_interval / 1000)
        except Exception as error:
            # Once a chunk has been delivered, retrying would duplicate output.
            if chunk_delivered:
                raise
            attempt_errors.append(str(error))
            if attempt >= max_attempts:
                retries = max(0, len(attempt_errors) - 1)
                retry_label = "retry" if retries == 1 else "retries"
                raise RuntimeError(
                    f"AI model request failed after {retries} {retry_label} "
                    f"({len(attempt_errors)}/{max_attempts} attempts). "
                    f"Last error: {error}"
                ) from error
            logger.warning(
                f"AI call failed (attempt {attempt}/{max_attempts}), retrying in "
                f"{retry_interval}ms... Error: {error}"
            )
            await asyncio.sleep(retry_interval / 1000)

    raise RuntimeError("AI model request failed: unknown error")


async def call_ai_with_string_response(
    messages: List[dict],
    model_runtime: ModelRuntime,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call AI expecting a plain-text response (used by custom planners)."""
    return await call_generative_ai(messages, model_runtime, options)
