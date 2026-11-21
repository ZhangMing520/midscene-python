"""Chat-completion call options (upstream chat-completion/types.ts)."""

from typing import Any, Callable, Dict, Optional, TypedDict


class ChatCompletionCallOptions(TypedDict, total=False):
    request_body: Dict[str, Any]
    adapter: Any
    on_chunk: Optional[Callable[[Dict[str, Any]], Any]]
