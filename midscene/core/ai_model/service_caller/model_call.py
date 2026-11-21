"""Single model call preparation and transport (upstream service-caller/model-call.ts)."""

from typing import Any, Dict, List, Optional
import json
import inspect
import httpx
from loguru import logger
from midscene.core.siwc import SiwcTokenExpiredError

from midscene.core.ai_model.service_caller.types import (
    AIResponseParseError,
)
from midscene.core.ai_model.service_caller.openai.responses import (
    _parse_responses_payload,
)
from midscene.core.ai_model.service_caller.utils import (
    has_usable_text,
)

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
