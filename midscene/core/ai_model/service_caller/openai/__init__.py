"""OpenAI-compatible protocol layer (upstream service-caller/openai)."""

from midscene.core.ai_model.service_caller.openai.call_openai import call_openai
from midscene.core.ai_model.service_caller.openai.chat_completion import (
    prepare_chat_completion,
)
from midscene.core.ai_model.service_caller.openai.responses import (
    prepare_responses,
)
from midscene.core.ai_model.service_caller.openai.siwc import (
    SiwcTokenExpiredError,
    prepare_siwc_call,
    siwc_token_manager,
)

__all__ = [
    "SiwcTokenExpiredError",
    "call_openai",
    "prepare_chat_completion",
    "prepare_responses",
    "prepare_siwc_call",
    "siwc_token_manager",
]
