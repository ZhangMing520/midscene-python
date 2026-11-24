"""OpenRouter base-URL detection (upstream ai-model/model-adapter/is-openrouter.ts)."""

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def is_open_router(base_url: str | None = None) -> bool:
    return base_url == OPENROUTER_BASE_URL


# Backward-compatible private alias used across the model adapters.
_is_openrouter = is_open_router


__all__ = ["OPENROUTER_BASE_URL", "_is_openrouter", "is_open_router"]
