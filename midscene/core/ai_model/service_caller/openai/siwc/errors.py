"""SIWC error types and stage wrapping (upstream openai/siwc/errors.ts)."""

from typing import Awaitable, Callable, TypeVar

import httpx

T = TypeVar("T")


class SiwcTokenExpiredError(Exception):
    """Signals an expired SIWC token that may be refreshed before replaying."""


class SiwcError(Exception):
    pass


async def with_siwc_stage(stage: str, action: Callable[[], Awaitable[T]]) -> T:
    """Run an auth step and prefix any failure with the stage name."""
    try:
        return await action()
    except Exception as error:
        # Browser callers often display only message; keep the cause readable there too.
        raise SiwcError(f"Stage: {stage}\n{error}") from error


async def token_response_error(response: httpx.Response) -> SiwcError:
    return SiwcError(
        f"HTTP status: {response.status_code}\nResponse body: {response.text}"
    )
