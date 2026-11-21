"""System One client call (upstream system-one/call-system-one.ts)."""

import json
import uuid
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.system_one.prepare_system_one import (
    prepare_system_one,
)
from midscene.core.ai_model.service_caller.system_one.schema import (
    SystemOneError,
    validate_system_one_response,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError


async def call_system_one(
    model_runtime: ModelRuntime,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    """Send a System One request; returns {content, usage, raw_response...}.

    The raw System One response JSON is returned as `content` (upstream
    semantics); callers parse `answers` themselves.
    """
    config = model_runtime.config
    prepared = prepare_system_one(config, request, model_runtime.execution_id)
    questions: Dict[str, Any] = prepared["questions"]

    proxy = prepared.get("proxy")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(resolve_effective_timeout(config.get("timeout"))),
            proxy=proxy,
        ) as client:
            response = await client.post(
                prepared["url"],
                headers=prepared["headers"],
                content=prepared["body"],
            )
    except httpx.TimeoutException as e:
        raise SystemOneError(f"Jev request timeout: {e}") from e

    body_text = response.text
    if response.status_code >= 400:
        raise SystemOneError(
            f"Jev request failed ({response.status_code}): {body_text[:4000]}"
        )

    try:
        payload = json.loads(body_text)
        result = validate_system_one_response(payload)
        for name, question in questions.items():
            answer = result["answers"].get(name)
            if not answer or answer.get("type") != question.get("type"):
                raise SystemOneError(f"Missing or invalid Jev answer: {name}")
            if question["type"] == "choice":
                if answer["choice"] not in (question.get("criteria") or {}):
                    raise SystemOneError(f"Invalid Jev choice: {name}")
    except (json.JSONDecodeError, SystemOneError) as error:
        raise AIResponseParseError(
            f"Invalid System One response: {error}", body_text
        ) from error

    usage_data = result.get("usage") or {}
    input_tokens = usage_data.get("input_tokens")
    output_tokens = usage_data.get("output_tokens")
    usage = None
    if input_tokens is not None and output_tokens is not None:
        from midscene.core.ai_model.service_caller.utils import build_usage_info

        usage = build_usage_info(
            raw_usage={
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            model_config=config,
            time_cost=None,
            retry_count=0,
            request_id=None,
            response_model_name=result.get("model"),
            internal_call_id=f"so_{uuid.uuid4().hex[:12]}",
        )

    return {
        "content": body_text,
        "answers": result["answers"],
        "usage": usage,
        "response_model_name": result.get("model"),
    }


def resolve_effective_timeout(timeout: Optional[float]) -> Optional[float]:
    if timeout is None:
        return 180.0
    if timeout <= 0:
        return None
    return float(timeout)


__all__ = ["call_system_one", "logger", "resolve_effective_timeout"]
