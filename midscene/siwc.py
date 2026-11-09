"""Public SIWC authorization API (upstream packages/core/src/siwc.ts).

For external login flows and CI session owners. The implementation lives in
`midscene.core.ai_model.siwc`; this module only re-exports it.
"""

from .core.ai_model.siwc import (
    SiwcError,
    SiwcLoginAttempt,
    create_siwc_authorization,
    exchange_siwc_code,
    parse_siwc_callback,
    refresh_siwc_credentials,
)

__all__ = [
    "SiwcError",
    "SiwcLoginAttempt",
    "create_siwc_authorization",
    "exchange_siwc_code",
    "parse_siwc_callback",
    "refresh_siwc_credentials",
]
