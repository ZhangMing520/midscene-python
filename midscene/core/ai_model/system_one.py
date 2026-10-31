"""System One (TypeSafe / Jev) protocol client.

Synced from upstream packages/core/src/ai-model/service-caller/system-one/*
and models/jev/*.
"""

import json
import re
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger

from .adapters import ModelRuntime


class SystemOneError(Exception):
    pass


# ---------------------------------------------------------------------------
# Schema (schema.ts)
# ---------------------------------------------------------------------------

def validate_system_one_response(payload: Any) -> Dict[str, Any]:
    """Validate a System One response (answers + usage)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise SystemOneError(
            f"invalid System One response: {json.dumps(payload)[:500]}"
        )

    for name, answer in payload["answers"].items():
        answer_type = answer.get("type")
        if answer_type == "noul":
            _validate_probability(answer.get("noul"))
        elif answer_type == "choice":
            if not isinstance(answer.get("choice"), str):
                raise SystemOneError(f"invalid System One choice answer: {name}")
        elif answer_type == "box":
            box = answer.get("box") or {}
            left, right = box.get("left"), box.get("right")
            top, bottom = box.get("top"), box.get("bottom")
            for value in (left, right, top, bottom):
                _validate_probability(value)
            if not (left < right and top < bottom):
                raise SystemOneError("Invalid box edges")
        else:
            raise SystemOneError(f"unknown System One answer type: {answer_type}")

    usage = payload.get("usage")
    if usage is not None:
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                usage[key] = None
    return payload


def _validate_probability(value: Any) -> None:
    if not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise SystemOneError(f"invalid probability value: {value!r}")


# ---------------------------------------------------------------------------
# Image encoding (utils.ts)
# ---------------------------------------------------------------------------

def encode_system_one_images(
    images: Optional[Dict[str, str]], is_openrouter: bool
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Encode reference images into inline parts (OpenRouter) or assets map."""
    assets: Dict[str, Any] = {}
    image_state: Dict[str, Any] = {}
    for name, data_url in (images or {}).items():
        if is_openrouter:
            # OpenRouter ignores TypeSafe's top-level assets map; send inline
            # image_url parts instead of asset references.
            image_state[name] = {
                "type": "image_url",
                "image_url": {"url": data_url},
            }
            continue
        reference = uuid.uuid4().hex
        match = re.match(r"^data:image/(png|jpe?g);base64,(.+)$", data_url)
        if not match:
            raise SystemOneError(
                "System One images must be prepared PNG or JPEG data URLs"
            )
        assets[reference] = {
            "type": "image",
            "format": "png" if match.group(1) == "png" else "jpg",
            "data_base64": match.group(2),
        }
        image_state[name] = reference
    return image_state, assets


def resolve_system_one_endpoint(config: Dict[str, Any]) -> str:
    endpoint = config.get("endpoint")
    if endpoint:
        return endpoint
    base_url = config.get("openaiBaseURL")
    if not base_url:
        raise SystemOneError(
            "When using the System One API, you must provide "
            "MIDSCENE_*_MODEL_ENDPOINT or MIDSCENE_*_MODEL_BASE_URL."
        )
    return base_url.rstrip("/") + "/systemone"


# ---------------------------------------------------------------------------
# Call (prepare-system-one.ts + call-system-one.ts)
# ---------------------------------------------------------------------------

def prepare_system_one(
    config: Dict[str, Any], request: Dict[str, Any]
) -> Dict[str, Any]:
    if not config.get("openaiApiKey"):
        raise SystemOneError("Jev requires MIDSCENE_*_MODEL_API_KEY")
    protocol = config.get("protocol")
    if protocol and protocol != "openai-chat":
        raise SystemOneError("Jev uses System One, not the Responses API")

    url = resolve_system_one_endpoint(config)
    is_openrouter = urlparse(url).hostname == "openrouter.ai"
    image_state, assets = encode_system_one_images(
        request.get("images"), is_openrouter
    )
    body: Dict[str, Any] = {
        **(config.get("extraBody") or {}),
        "model": config.get("modelName"),
        "state": {**request.get("state", {}), **image_state},
        "questions": request.get("questions", {}),
    }
    if not is_openrouter and assets:
        body["assets"] = assets
    serialized_body = json.dumps(body, ensure_ascii=False)
    if len(serialized_body.encode("utf-8")) > 32 * 1024 * 1024:
        raise SystemOneError("Jev request exceeds the 32 MiB body limit")

    headers: Dict[str, str] = {
        "Authorization": f"Bearer {config.get('openaiApiKey')}",
        "Content-Type": "application/json",
        "TypeSafe-Danger-Zone-Images": "true",
        "x-midscene-version": __import__("midscene").__version__,
    }
    extra_headers = (config.get("openaiExtraConfig") or {}).get("defaultHeaders")
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})

    return {
        "url": url,
        "body": serialized_body,
        "questions": request.get("questions", {}),
        "headers": headers,
        "proxy": config.get("httpProxy") or config.get("socksProxy"),
    }


async def call_system_one(
    model_runtime: ModelRuntime,
    request: Dict[str, Any],
) -> Dict[str, Any]:
    """Send a System One request; returns {content, usage, raw_response...}.

    The raw System One response JSON is returned as `content` (upstream
    semantics); callers parse `answers` themselves.
    """
    config = model_runtime.config
    prepared = prepare_system_one(config, request)
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
    except json.JSONDecodeError as e:
        raise SystemOneError(f"invalid System One JSON response: {e}") from e
    result = validate_system_one_response(payload)

    for name, question in questions.items():
        answer = result["answers"].get(name)
        if not answer or answer.get("type") != question.get("type"):
            raise SystemOneError(f"Missing or invalid Jev answer: {name}")
        if question["type"] == "choice":
            if answer["choice"] not in (question.get("criteria") or {}):
                raise SystemOneError(f"Invalid Jev choice: {name}")

    usage_data = result.get("usage") or {}
    input_tokens = usage_data.get("input_tokens")
    output_tokens = usage_data.get("output_tokens")
    usage = None
    if input_tokens is not None and output_tokens is not None:
        from .caller import build_usage_info

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


__all__ = [
    "SystemOneError",
    "call_system_one",
    "encode_system_one_images",
    "prepare_system_one",
    "resolve_system_one_endpoint",
    "validate_system_one_response",
    "logger",
]
