"""Chat-completion call options (upstream chat-completion/types.ts)."""

from collections.abc import Callable
from typing import Any, TypedDict


class ChatCompletionCallOptions(TypedDict, total=False):
    request_body: dict[str, Any]
    adapter: Any
    on_chunk: Callable[[dict[str, Any]], Any] | None
