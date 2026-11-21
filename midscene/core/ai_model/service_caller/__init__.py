"""Service-caller layer (upstream packages/core/src/ai-model/service-caller)."""

from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
    call_generative_ai,
)
from midscene.core.ai_model.service_caller.openai.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.openai.responses import (
    prepare_responses,
)
from midscene.core.ai_model.service_caller.request_timeout import (
    resolve_effective_timeout_ms,
)
from midscene.core.ai_model.service_caller.types import (
    AIResponseParseError,
    CodexAppServerNotSupportedError,
)
from midscene.core.ai_model.service_caller.utils import (
    build_usage_info,
)

__all__ = [
    "AIResponseParseError",
    "CodexAppServerNotSupportedError",
    "build_usage_info",
    "call_ai_with_string_response",
    "call_generative_ai",
    "prepare_chat_completion",
    "prepare_responses",
    "resolve_effective_timeout_ms",
]
