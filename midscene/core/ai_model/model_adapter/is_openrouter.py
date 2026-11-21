"""OpenRouter base-URL detection (upstream ai-model/model-adapter/is-openrouter.ts)."""

from typing import Optional

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _is_openrouter(base_url: Optional[str]) -> bool:
    return base_url == OPENROUTER_BASE_URL
