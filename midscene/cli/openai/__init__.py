"""ChatGPT (SIWC) CLI helpers (upstream packages/cli/src/openai)."""

from midscene.cli.openai.credentials import (
    OpenAICredentials,
    Registration,
    get_credential_storage,
)
from midscene.cli.openai.errors import (
    SiwcError,
    describe_siwc_error,
    token_response_error,
    with_siwc_stage,
)
from midscene.cli.openai.login import login_with_openai

__all__ = [
    "OpenAICredentials",
    "Registration",
    "SiwcError",
    "describe_siwc_error",
    "get_credential_storage",
    "login_with_openai",
    "token_response_error",
    "with_siwc_stage",
]
