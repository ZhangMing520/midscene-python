"""Temperature overrides and semantic-retry nudge (upstream temperature-with-semantic-retry.ts)."""

from typing import Any, TypeVar

from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

_T = TypeVar("_T")


def get_temperature_with_semantic_retry(
    temperature: _T,
    user_temperature: float | None = None,
    semantic_retry_attempt: int = 0,
) -> Any:
    """Return the effective temperature for one model call.

    Only perturb the default deterministic request after a semantic parse
    failure: preserve an explicit user temperature, and avoid adding a
    temperature to adapters whose normal parameters do not include one.
    """
    if semantic_retry_attempt > 0 and user_temperature is None and temperature == 0:
        return 0.2
    return temperature


def _apply_temperature(
    config: dict[str, Any],
    user_config: ModelRequestUserConfig,
    allow_override: bool = True,
) -> dict[str, Any]:
    """Apply the user temperature; the 'unset' sentinel removes the default."""
    if not allow_override:
        config.pop("temperature", None)
        return config
    temperature = user_config.get("temperature")
    if temperature == "unset":
        config.pop("temperature", None)
    elif temperature is not None:
        config["temperature"] = temperature
    return config


def _apply_semantic_retry_temperature(
    request_body: dict[str, Any],
    model_config: dict[str, Any],
    options: dict[str, Any],
) -> None:
    """Nudge the deterministic default temperature after a parse failure."""
    attempt = options.get("semanticRetryAttempt") or 0
    if (
        attempt > 0
        and model_config.get("temperature") is None
        and request_body.get("temperature") == 0
    ):
        request_body["temperature"] = 0.2


__all__ = [
    "_apply_semantic_retry_temperature",
    "_apply_temperature",
    "get_temperature_with_semantic_retry",
]
