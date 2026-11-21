"""Temperature overrides and semantic-retry nudge (upstream temperature-with-semantic-retry.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

def _apply_temperature(
    config: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    allow_override: bool = True,
) -> Dict[str, Any]:
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
    request_body: Dict[str, Any],
    model_config: Dict[str, Any],
    options: Dict[str, Any],
) -> None:
    """Nudge the deterministic default temperature after a parse failure."""
    attempt = options.get("semanticRetryAttempt") or 0
    if (
        attempt > 0
        and model_config.get("temperature") is None
        and request_body.get("temperature") == 0
    ):
        request_body["temperature"] = 0.2
