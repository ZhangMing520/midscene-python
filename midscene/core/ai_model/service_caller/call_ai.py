"""Retry/parse loop (upstream service-caller/call-ai.ts)."""

from typing import Any, Dict, List, Optional
import asyncio
import json
import time
from loguru import logger
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.siwc import SiwcTokenExpiredError, prepare_siwc_call, siwc_token_manager

from midscene.core.ai_model.service_caller.model_call import (
    _finalize_result,
    _post_json,
    _request_headers,
)
from midscene.core.ai_model.service_caller.openai.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.openai.responses import (
    _parse_responses_payload,
    prepare_responses,
)
from midscene.core.ai_model.service_caller.types import DEFAULT_MODEL_PROTOCOL
from midscene.core.ai_model.service_caller.request_timeout import (
    resolve_effective_timeout_ms,
)
from midscene.core.ai_model.service_caller.types import (
    AIResponseParseError,
    CodexAppServerNotSupportedError,
)
from midscene.core.ai_model.service_caller.utils import (
    build_usage_info,
    extract_content_and_reasoning,
    is_codex_app_server_provider,
    next_internal_call_id,
    normalize_retry_count,
)

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
                parse_retry_count=options.get("semanticRetryAttempt") or 0,
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
                current_key,
                {
                    "httpProxy": model_config.get("httpProxy"),
                    "socksProxy": model_config.get("socksProxy"),
                },
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
