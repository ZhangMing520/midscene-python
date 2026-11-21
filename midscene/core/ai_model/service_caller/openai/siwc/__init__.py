"""SIWC public surface (upstream openai/siwc/index.ts)."""

from midscene.core.ai_model.service_caller.openai.siwc.authorization import (
    DEFAULT_DYNAMIC_CLIENT_ID,
    ISSUER,
    RESOURCE,
    SiwcLoginAttempt,
    create_siwc_authorization,
    exchange_siwc_code,
    parse_siwc_callback,
)
from midscene.core.ai_model.service_caller.openai.siwc.credential_storage import (
    REAUTHORIZATION_HINT,
    SIWC_AUTH_STORAGE_KEY,
    get_credential_storage,
)
from midscene.core.ai_model.service_caller.openai.siwc.errors import (
    SiwcError,
    SiwcTokenExpiredError,
    token_response_error,
    with_siwc_stage,
)
from midscene.core.ai_model.service_caller.openai.siwc.prepare_call import (
    prepare_siwc_call,
)
from midscene.core.ai_model.service_caller.openai.siwc.refresh import (
    refresh_siwc_credentials,
)
from midscene.core.ai_model.service_caller.openai.siwc.token_manager import (
    SiwcTokenManager,
    siwc_token_manager,
)

__all__ = [
    "DEFAULT_DYNAMIC_CLIENT_ID",
    "ISSUER",
    "REAUTHORIZATION_HINT",
    "RESOURCE",
    "SIWC_AUTH_STORAGE_KEY",
    "SiwcError",
    "SiwcLoginAttempt",
    "SiwcTokenExpiredError",
    "SiwcTokenManager",
    "create_siwc_authorization",
    "exchange_siwc_code",
    "get_credential_storage",
    "parse_siwc_callback",
    "prepare_siwc_call",
    "refresh_siwc_credentials",
    "siwc_token_manager",
    "token_response_error",
    "with_siwc_stage",
]
