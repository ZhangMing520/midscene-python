"""CLI credential storage access (upstream packages/cli/src/openai/credentials.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.service_caller.openai.siwc.credential_storage import (
    REAUTHORIZATION_HINT,
    SIWC_AUTH_STORAGE_KEY,
    _credentials_path,
    _read_credentials,
    _save_credentials,
    get_credential_storage,
)

OpenAICredentials = Dict[str, Any]
Registration = Dict[str, Any]

__all__ = [
    "OpenAICredentials",
    "REAUTHORIZATION_HINT",
    "Registration",
    "SIWC_AUTH_STORAGE_KEY",
    "_credentials_path",
    "_read_credentials",
    "_save_credentials",
    "get_credential_storage",
]
