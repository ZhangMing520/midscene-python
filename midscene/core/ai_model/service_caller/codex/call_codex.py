"""Codex app-server call preparation/execution (upstream codex/call-codex.ts)."""

import asyncio
import inspect
import time
import traceback
from collections.abc import Callable
from typing import Any

from midscene.core.ai_model.model_adapter.codex_app_server import (
    build_default_codex_app_server_params,
)
from midscene.core.ai_model.service_caller.codex.codex_app_server import (
    call_ai_with_codex_app_server,
)
from midscene.core.ai_model.service_caller.utils import resolve_image_detail


def _throw_if_aborted(abort_signal: Any) -> None:
    if abort_signal is None:
        return
    is_set = getattr(abort_signal, "is_set", None)
    if callable(is_set) and is_set():
        raise RuntimeError("codex app-server request aborted")
    if getattr(abort_signal, "aborted", False):
        raise RuntimeError("codex app-server request aborted")


def _build_resolve_image_detail(
    adapter: Any,
    model_config: dict[str, Any],
    options: dict[str, Any],
) -> Callable[[dict[str, Any]], str]:
    intent = model_config.get("intent")
    requires_original = bool(options.get("requiresOriginalImageDetail"))
    adapter_resolver = getattr(adapter, "resolve_image_detail", None)
    if callable(adapter_resolver):

        def resolve_from_adapter(input_data: dict[str, Any]) -> str:
            return adapter_resolver(
                {
                    "imageDetail": input_data.get("imageDetail"),
                    "intent": intent,
                    "requiresOriginalImageDetail": requires_original,
                }
            )

        return resolve_from_adapter

    def resolve_default(input_data: dict[str, Any]) -> str:
        return resolve_image_detail(
            input_data.get("imageDetail") or "high", intent, requires_original
        )

    return resolve_default


def prepare_codex_call(
    messages: list[dict[str, Any]],
    model_runtime: Any,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Codex turn params and the image-detail resolver for a call."""
    options = options or {}
    model_config = model_runtime.config
    adapter = model_runtime.adapter

    builder = getattr(adapter, "build_codex_app_server_params", None)
    if not callable(builder):
        builder = build_default_codex_app_server_params
    params_result = (
        builder(
            {
                "intent": model_config.get("intent"),
                "userConfig": {
                    "reasoningEnabled": model_config.get("reasoningEnabled"),
                    "reasoningEffort": model_config.get("reasoningEffort"),
                    "reasoningBudget": model_config.get("reasoningBudget"),
                },
                "requiresOriginalImageDetail": bool(
                    options.get("requiresOriginalImageDetail")
                ),
            }
        )
        or {}
    )

    return {
        "messages": messages,
        "resolve_image_detail": _build_resolve_image_detail(
            adapter, model_config, options
        ),
        "request_params": params_result.get("config") or {},
    }


async def call_codex(
    model_runtime: Any,
    options: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    request_params: dict[str, Any] | None = None,
    resolve_image_detail: Callable[[dict[str, Any]], str] | None = None,
    record_event: Callable[[dict[str, Any]], Any] | None = None,
    request_signal: Any = None,
) -> dict[str, Any]:
    """Run a Codex turn and return the same shape as ``call_openai``."""
    options = options or {}
    if resolve_image_detail is None:
        resolve_image_detail = _build_resolve_image_detail(
            model_runtime.adapter, model_runtime.config, options
        )

    protocol_chunk_sequence = 0
    codex_start_time = time.time()

    def record_codex_event(event: dict[str, Any]) -> None:
        nonlocal protocol_chunk_sequence
        if record_event is None:
            return
        payload = dict(event)
        if event.get("type") == "chunk":
            protocol_chunk_sequence += 1
            payload["sequence"] = protocol_chunk_sequence
        payload["attempt"] = 1
        payload["provider"] = "codex-app-server"
        result = record_event(payload)
        if inspect.isawaitable(result):
            asyncio.ensure_future(result)

    try:
        codex_result = await call_ai_with_codex_app_server(
            messages,
            model_runtime.config,
            {
                "stream": options.get("stream"),
                "on_chunk": options.get("onChunk") or options.get("on_chunk"),
                "params": request_params,
                "resolve_image_detail": resolve_image_detail,
                "abort_signal": request_signal,
                "on_record_event": record_codex_event
                if record_event is not None
                else None,
            },
        )
        _throw_if_aborted(request_signal)

        usage = codex_result.get("usage")
        protocol_metadata = codex_result.get("protocolMetadata") or {}
        content = codex_result.get("content")
        reasoning_content = codex_result.get("reasoning_content")
        time_cost = int((time.time() - codex_start_time) * 1000)

        if record_event is not None:
            record_codex_event(
                {
                    "type": "response",
                    "final": {
                        "content": content,
                        "reasoningContent": reasoning_content,
                        "usage": usage,
                        "timeCost": time_cost,
                        "protocol": protocol_metadata,
                    },
                }
            )

        return {
            "content": content,
            "reasoningContent": reasoning_content,
            "reasoning_content": reasoning_content,
            "rawUsage": usage,
            "requestId": protocol_metadata.get("turnId"),
            "timeCost": time_cost,
            "isStreamed": codex_result.get("isStreamed", False),
            "protocolMetadata": protocol_metadata,
        }
    except BaseException as error:
        if record_event is not None:
            record_codex_event(
                {
                    "type": "error",
                    "error": {
                        "name": type(error).__name__,
                        "message": str(error),
                        "stack": traceback.format_exc(),
                    },
                }
            )
        raise


__all__ = ["call_codex", "prepare_codex_call"]
