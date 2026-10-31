"""Semantic retry loop for AI call + parse.

Synced from upstream packages/core/src/ai-model/service-caller/semantic-retry.ts.
"""

import asyncio
from typing import Any, Awaitable, Callable, List, Optional, Union

from loguru import logger


def with_semantic_retry_feedback(
    messages: List[dict],
    previous_parse_error: Optional[Union[BaseException, str]] = None,
) -> List[dict]:
    """Append the previous parse error so the model can correct its output."""
    if not previous_parse_error:
        return messages

    if isinstance(previous_parse_error, BaseException):
        error_message = str(previous_parse_error)
    else:
        error_message = str(previous_parse_error)

    return messages + [
        {
            "role": "user",
            "content": (
                f"The previous response was invalid:\n{error_message}\n\n"
                "Please avoid the validation error above in this response."
            ),
        }
    ]


async def call_ai_and_parse_with_retry(
    call_ai: Callable[[int, Optional[Any]], Awaitable[Any]],
    parse_response: Callable[[Any], Any],
    to_parse_error: Callable[[Any, Any], Exception],
    parse_retry_times: int = 0,
    parse_retry_interval: int = 0,
    on_parse_retry: Optional[Callable[[Any, Any], None]] = None,
) -> Any:
    """Call AI and parse its response, retrying only on structural parse failures.

    Errors raised by call_ai() propagate as-is; only parse_response() failures
    trigger another model request.
    """
    try:
        normalized_retry_times = max(0, int(parse_retry_times))
    except (TypeError, ValueError):
        normalized_retry_times = 0
    try:
        normalized_retry_interval = max(0, int(parse_retry_interval))
    except (TypeError, ValueError):
        normalized_retry_interval = 0

    async def call_and_parse_once(
        remaining_retries: int,
        retry_attempt: int,
        previous_parse_error: Optional[Any] = None,
    ) -> Any:
        response = await call_ai(retry_attempt, previous_parse_error)
        try:
            return parse_response(response)
        except Exception as error:
            if remaining_retries > 0:
                if on_parse_retry is not None:
                    on_parse_retry(error, response)
                if normalized_retry_interval > 0:
                    await asyncio.sleep(normalized_retry_interval / 1000)
                return await call_and_parse_once(
                    remaining_retries - 1, retry_attempt + 1, error
                )
            raise to_parse_error(error, response)

    return await call_and_parse_once(normalized_retry_times, 0)


def _noop(*args, **kwargs):  # pragma: no cover
    return None


__all__ = [
    "call_ai_and_parse_with_retry",
    "with_semantic_retry_feedback",
    "logger",
]
