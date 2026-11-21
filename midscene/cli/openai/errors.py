"""CLI SIWC error helpers (upstream packages/cli/src/openai/errors.ts)."""

from typing import Any

from midscene.core.ai_model.service_caller.openai.siwc.errors import (
    SiwcError,
    token_response_error,
    with_siwc_stage,
)


def describe_siwc_error(error: Any) -> str:
    """Readable error details for terminal output (upstream inspect())."""
    return repr(error)


__all__ = [
    "SiwcError",
    "describe_siwc_error",
    "token_response_error",
    "with_siwc_stage",
]
