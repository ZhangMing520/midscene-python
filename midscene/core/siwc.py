"""SIWC (Sign-In with ChatGPT) auth mode for OpenAI models.

Implementation lives in the upstream-aligned package
``midscene.core.ai_model.service_caller.openai.siwc``; this module keeps the
historical ``midscene.core.siwc`` import path working.
"""

import httpx  # noqa: F401  (kept so tests can patch ``siwc.httpx``)

from midscene.core.ai_model.service_caller.openai.siwc import (  # noqa: F401
    DEFAULT_DYNAMIC_CLIENT_ID,
    ISSUER,
    REAUTHORIZATION_HINT,
    RESOURCE,
    SIWC_AUTH_STORAGE_KEY,
    SiwcError,
    SiwcLoginAttempt,
    SiwcTokenExpiredError,
    SiwcTokenManager,
    create_siwc_authorization,
    exchange_siwc_code,
    get_credential_storage,
    parse_siwc_callback,
    prepare_siwc_call,
    refresh_siwc_credentials,
    siwc_token_manager,
)
from midscene.core.ai_model.service_caller.openai.siwc.credential_storage import (  # noqa: F401
    _credentials_path,
    _read_credentials,
    _save_credentials,
)
from midscene.core.ai_model.service_caller.openai.siwc.network import (  # noqa: F401
    _fetch_jwks,
    _load_jwks,
    _select_jwk,
    _siwc_proxy,
    _verify_id_token,
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
]
