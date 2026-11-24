"""Shared caller helpers (upstream service-caller/utils.ts)."""

import inspect
import json
import math
import uuid
from typing import Any

from midscene.core.ai_model.models.registry import is_locate_intent
from midscene.core.ai_model.service_caller.types import AIResponseParseError

__all__ = ["AIResponseParseError"]

# Internal field name stamped onto usage info by the shared model call pipeline.
# Used for cross-path dedup when the provider does not return a request_id.
INTERNAL_CALL_ID_FIELD = "_midscene_call_id"


def stringify_for_debug(value: Any) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _get_error_message(error: Any) -> str:
    return str(error)


def to_error(error: Any) -> BaseException:
    if isinstance(error, BaseException):
        return error
    return Exception(str(error))


def append_ai_request_failure_summary(
    error: BaseException,
    attempt_errors: list[dict[str, Any]],
    max_attempts: int,
) -> BaseException:
    """Prefix the final error with the attempt count and prior failures."""
    failed_attempts = len(attempt_errors)
    retries = max(0, failed_attempts - 1)
    retry_label = "retry" if retries == 1 else "retries"
    original_message = _get_error_message(error)
    previous_attempt_errors = attempt_errors[:-1]

    message = (
        f"AI model request failed after {retries} {retry_label} "
        f"({failed_attempts}/{max_attempts} attempts). "
        f"Last error: {original_message}"
    )

    if previous_attempt_errors:
        details = "\n".join(
            f"Attempt {entry.get('attempt')}: {_get_error_message(entry.get('error'))}"
            for entry in previous_attempt_errors
        )
        message = f"{message}\nPrevious AI call attempt errors:\n{details}"

    # BaseException has no writable ``message`` attribute; args is the
    # equivalent surface used by str()/repr().
    error.args = (message,)
    return error


async def emit_stream_chunk(
    on_chunk: Any | None,
    content: str,
    reasoning_content: str,
    accumulated: str,
    is_complete: bool = False,
    usage: dict[str, Any] | None = None,
) -> None:
    """Deliver a CodeGenerationChunk to the caller (upstream onChunk)."""
    if on_chunk is None:
        return
    result = on_chunk(
        {
            "content": content,
            "reasoning_content": reasoning_content,
            "accumulated": accumulated,
            "isComplete": is_complete,
            "usage": usage,
        }
    )
    if inspect.isawaitable(result):
        await result


def has_usable_text(content: str | None) -> bool:
    return content is not None and content.strip() != ""


def normalize_retry_count(retry_count: Any) -> int:
    if (
        isinstance(retry_count, bool)
        or not isinstance(retry_count, (int, float))
        or not math.isfinite(retry_count)
    ):
        return 1
    return max(0, int(retry_count))


def next_internal_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


CODEX_PROVIDER_SCHEME = "codex://"


def is_codex_app_server_provider(base_url: str | None) -> bool:
    if not base_url:
        return False
    return base_url.strip().lower().startswith(CODEX_PROVIDER_SCHEME)


def resolve_image_detail(
    adapter_detail: str, intent: str | None, requires_original: bool
) -> str:
    if requires_original or is_locate_intent(intent):
        return "high"  # 'original' is not portable across OpenAI-compatible servers
    return adapter_detail or "high"


def extract_content_and_reasoning(
    message: dict[str, Any] | None, reasoning_keys: list[str]
) -> dict[str, str]:
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


def map_responses_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
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
    raw_usage: dict[str, Any] | None,
    model_config: dict[str, Any],
    time_cost: int | None,
    retry_count: int,
    request_id: str | None,
    response_model_name: str | None,
    internal_call_id: str,
    parse_retry_count: int = 0,
) -> dict[str, Any] | None:
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
        # `retry` predates the upstream metric split; keep it as the sum.
        "retry": retry_count + parse_retry_count,
        "request_retry_count": retry_count,
        "parse_retry_count": parse_retry_count,
        "request_id": request_id,
        "model_name": response_model_name or model_config.get("modelName"),
        "model_description": model_config.get("modelDescription", ""),
        "model_family": model_config.get("modelFamily"),
        "intent": model_config.get("intent"),
        "slot": model_config.get("slot"),
        INTERNAL_CALL_ID_FIELD: internal_call_id,
    }
