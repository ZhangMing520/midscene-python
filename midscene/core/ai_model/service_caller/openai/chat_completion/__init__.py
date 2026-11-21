"""OpenAI chat-completion protocol (upstream openai/chat-completion)."""

from midscene.core.ai_model.service_caller.openai.chat_completion.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.non_stream import (
    call_chat_completion_non_streaming,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.stream import (
    call_chat_completion_stream,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.types import (
    ChatCompletionCallOptions,
)
from midscene.core.ai_model.service_caller.openai.chat_completion.utils import (
    resolve_content_with_reasoning_fallback,
    to_chat_messages,
)

__all__ = [
    "ChatCompletionCallOptions",
    "call_chat_completion_non_streaming",
    "call_chat_completion_stream",
    "prepare_chat_completion",
    "resolve_content_with_reasoning_fallback",
    "to_chat_messages",
]
