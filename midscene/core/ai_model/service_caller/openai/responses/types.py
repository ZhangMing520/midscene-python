"""Responses call options (upstream responses/types.ts)."""

from typing import Any, Callable, Dict, Optional, TypedDict


class ResponsesCallOptions(TypedDict, total=False):
    request_body: Dict[str, Any]
    on_chunk: Optional[Callable[[Dict[str, Any]], Any]]
