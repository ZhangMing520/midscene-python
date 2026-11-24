"""Retry/parse loop (upstream service-caller/call-ai.ts)."""

import asyncio
import time
from typing import Any

from loguru import logger

from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.codex.call_codex import (
    call_codex,
    prepare_codex_call,
)
from midscene.core.ai_model.service_caller.model_call_recorder import (
    is_model_call_recording_enabled,
    record_model_call_event,
)
from midscene.core.ai_model.service_caller.openai.call_openai import call_openai
from midscene.core.ai_model.service_caller.openai.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.openai.responses import (
    prepare_responses,
)
from midscene.core.ai_model.service_caller.openai.siwc import (
    SiwcTokenExpiredError,
    prepare_siwc_call,
    siwc_token_manager,
)
from midscene.core.ai_model.service_caller.request_timeout import (
    resolve_effective_timeout_ms,
    run_with_abort_signal,
    wait_for_retry,
)
from midscene.core.ai_model.service_caller.system_one import call_system_one
from midscene.core.ai_model.service_caller.types import (
    DEFAULT_MODEL_PROTOCOL,
    CodexAppServerNotSupportedError,
)
from midscene.core.ai_model.service_caller.utils import (
    append_ai_request_failure_summary,
    build_usage_info,
    is_codex_app_server_provider,
    next_internal_call_id,
    normalize_retry_count,
    to_error,
)

# Kept for compatibility with callers importing the error from this module.
__all__ = [
    "CodexAppServerNotSupportedError",
    "call_ai_with_string_response",
    "call_generative_ai",
    "call_system_one_ai",
]


async def call_generative_ai(
    messages: list[dict],
    original_model_runtime: ModelRuntime,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the model and return {content, reasoning_content, usage, ...}."""
    options = dict(options or {})
    model_runtime, siwc_options = await prepare_siwc_call(
        original_model_runtime, options
    )
    if siwc_options:
        options.update(siwc_options)

    model_config = model_runtime.config
    protocol = model_config.get("protocol") or DEFAULT_MODEL_PROTOCOL
    codex_provider = is_codex_app_server_provider(model_config.get("openaiBaseURL"))

    if not codex_provider:
        if protocol == "openai-responses":
            if not model_runtime.adapter.supports_protocol("openai-responses"):
                raise ValueError(
                    f'Model adapter "{model_config.get("modelFamily") or "default"}" '
                    'does not support protocol "openai-responses"'
                )
        elif protocol != "openai-chat":
            raise ValueError(f"Unsupported model protocol: {protocol}")

    api_key = model_config.get("openaiApiKey")
    effective_timeout = resolve_effective_timeout_ms(model_config.get("timeout"))
    internal_call_id = next_internal_call_id()

    stream_requested = (
        options.get("stream") is True or model_config.get("streamMode") == "stream"
    )
    on_chunk = options.get("onChunk") or options.get("on_chunk")
    if options.get("stream") is True and on_chunk is None:
        raise RuntimeError(
            "onChunk is required when stream: true is explicitly specified"
        )
    chunk_delivered = False

    def _track_chunk(chunk: dict[str, Any]) -> Any:
        nonlocal chunk_delivered
        chunk_delivered = True
        return on_chunk(chunk)

    chunk_callback = _track_chunk if on_chunk is not None else None

    if codex_provider:
        prepared = prepare_codex_call(messages, model_runtime, options)
    elif protocol == "openai-responses":
        prepared = prepare_responses(messages, model_runtime, options)
    else:
        prepared = prepare_chat_completion(messages, model_runtime, options)

    max_attempts = normalize_retry_count(model_config.get("retryCount")) + 1
    retry_interval = model_config.get("retryInterval") or 2000
    attempt_errors: list[dict[str, Any]] = []
    start_time = time.time()
    attempt = 0
    siwc_refreshed = False
    recording_enabled = is_model_call_recording_enabled()
    execution_id = getattr(model_runtime, "execution_id", None)

    while attempt < max_attempts:
        attempt += 1

        def record_event(
            event: dict[str, Any],
            _attempt: int = attempt,
            _model_config: dict[str, Any] = model_config,
        ) -> None:
            record_model_call_event(
                {
                    "executionId": execution_id,
                    "callId": internal_call_id,
                    "semanticRetryAttempt": options.get("semanticRetryAttempt"),
                    "slot": _model_config.get("slot"),
                    "intent": _model_config.get("intent"),
                    "modelFamily": _model_config.get("modelFamily"),
                    "modelFallback": getattr(model_runtime, "model_fallback", None),
                    **event,
                    "attempt": _attempt,
                }
            )

        try:
            if codex_provider:
                codex_options = dict(options)
                codex_options["stream"] = stream_requested
                if chunk_callback is not None:
                    codex_options["onChunk"] = chunk_callback
                codex_call = call_codex(
                    model_runtime,
                    codex_options,
                    messages,
                    prepared["request_params"],
                    resolve_image_detail=prepared["resolve_image_detail"],
                    record_event=record_event if recording_enabled else None,
                )
                if effective_timeout is not None:
                    parsed = await asyncio.wait_for(
                        codex_call, timeout=effective_timeout / 1000
                    )
                else:
                    parsed = await codex_call
            else:
                parsed = await call_openai(
                    model_runtime,
                    protocol,
                    prepared,
                    stream_requested,
                    on_chunk=chunk_callback,
                    effective_timeout=effective_timeout,
                    execution_id=execution_id,
                    record_event=record_event if recording_enabled else None,
                )
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
                "content": parsed.get("content"),
                "reasoningContent": parsed.get("reasoningContent"),
                "rawAssistantOutput": parsed.get("rawAssistantOutput"),
                "rawUsage": parsed.get("rawUsage"),
                "requestId": parsed.get("requestId"),
                "responseModelName": parsed.get("responseModelName"),
                "usage": usage,
                "reasoning_content": parsed.get("reasoningContent"),
                "raw_assistant_output": parsed.get("rawAssistantOutput"),
            }
        except SiwcTokenExpiredError as siwc_error:
            # One authentication retry, independent of the normal retryCount.
            if siwc_refreshed:
                raise RuntimeError("SIWC token rejected after refresh") from siwc_error
            current_key = model_config.get("openaiApiKey") or api_key
            if not current_key:
                raise RuntimeError("Missing rejected SIWC access token") from siwc_error
            refreshed_key = await siwc_token_manager.refresh_access_token(
                current_key,
                {
                    "httpProxy": model_config.get("httpProxy"),
                    "socksProxy": model_config.get("socksProxy"),
                },
            )
            siwc_refreshed = True
            model_config = {**model_config, "openaiApiKey": refreshed_key}
            # Keep adapter, usage callback and execution id on the same runtime.
            model_runtime.config = model_config
            api_key = refreshed_key
            attempt -= 1
            continue
        except Exception as error:
            abort_signal = options.get("abortSignal") or options.get("abort_signal")
            if abort_signal is not None:
                abort_signal.throw_if_aborted()
            # Once a chunk has been delivered, retrying would duplicate output.
            if chunk_delivered:
                raise
            last_error = to_error(error)
            if isinstance(last_error, TimeoutError):
                # Public contract: a hard timeout surfaces as RuntimeError so
                # callers can rely on the retry summary and error type.
                last_error = RuntimeError(
                    str(last_error) or f"AI call timed out after {effective_timeout}ms"
                )
            attempt_errors.append({"attempt": attempt, "error": last_error})
            if attempt >= max_attempts:
                raise append_ai_request_failure_summary(
                    last_error, attempt_errors, max_attempts
                ) from last_error
            logger.warning(
                f"AI call failed (attempt {attempt}/{max_attempts}), retrying in "
                f"{retry_interval}ms... Error: {last_error}"
            )
            await wait_for_retry(retry_interval, abort_signal)

    raise RuntimeError("AI model request failed: unknown error")


async def call_system_one_ai(
    request: dict[str, Any],
    model_runtime: ModelRuntime,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the System One (Jev) protocol with the shared retry/timeout policy."""
    options = dict(options or {})
    abort_signal = options.get("abortSignal") or options.get("abort_signal")
    if abort_signal is not None:
        abort_signal.throw_if_aborted()
    if options.get("stream"):
        raise RuntimeError("Jev does not support streaming output")
    if model_runtime.config.get("modelFamily") != "jev":
        raise RuntimeError(
            "System One currently only supports the Jev model family in Midscene"
        )

    max_attempts = normalize_retry_count(model_runtime.config.get("retryCount")) + 1
    retry_interval = model_runtime.config.get("retryInterval")
    if retry_interval is None:
        retry_interval = 2000
    effective_timeout = resolve_effective_timeout_ms(
        model_runtime.config.get("timeout")
    )
    attempt_errors: list[dict[str, Any]] = []
    start_time = time.time()

    for attempt in range(1, max_attempts + 1):
        if abort_signal is not None:
            abort_signal.throw_if_aborted()
        try:
            if abort_signal is not None:
                parsed = await run_with_abort_signal(
                    abort_signal,
                    lambda: call_system_one(model_runtime, request),
                )
            else:
                parsed = await call_system_one(model_runtime, request)
            time_cost = int((time.time() - start_time) * 1000)
            result = {
                "content": parsed.get("content"),
                "answers": parsed.get("answers"),
                "usage": parsed.get("usage"),
                "responseModelName": parsed.get("response_model_name"),
                "isStreamed": False,
                "timeCost": time_cost,
            }
            if result["usage"] and model_runtime.on_usage:
                model_runtime.on_usage(result["usage"])
            return result
        except Exception as error:
            if abort_signal is not None:
                abort_signal.throw_if_aborted()
            last_error = to_error(error)
            if isinstance(last_error, TimeoutError):
                # Public contract: a hard timeout surfaces as RuntimeError so
                # callers can rely on the retry summary and error type.
                last_error = RuntimeError(
                    str(last_error) or f"AI call timed out after {effective_timeout}ms"
                )
            attempt_errors.append({"attempt": attempt, "error": last_error})
            if attempt >= max_attempts:
                raise append_ai_request_failure_summary(
                    last_error, attempt_errors, max_attempts
                ) from last_error
            await wait_for_retry(retry_interval, abort_signal)

    raise RuntimeError("AI model request failed: unknown error")


async def call_ai_with_string_response(
    messages: list[dict],
    model_runtime: ModelRuntime,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call AI expecting a plain-text response (used by custom planners)."""
    return await call_generative_ai(messages, model_runtime, options)
