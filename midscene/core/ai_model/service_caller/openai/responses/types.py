"""Responses call options (upstream responses/types.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict


class ResponsesCallOptions(TypedDict, total=False):
    request_body: dict[str, Any]
    on_chunk: Callable[[dict[str, Any]], Any] | None
