"""Order-sensitivity judgement for locate cache features.

Synced from upstream packages/core/src/ai-model/workflows/insight/order-sensitive.ts.
"""

from typing import Any, Dict, Optional

from loguru import logger

from ..adapters import ModelRuntime
from ..caller import call_generative_ai
from ..json_utils import parse_model_response_json
from ..prompts.order_sensitive import (
    order_sensitive_judge_prompt,
    system_prompt_to_judge_order_sensitive,
)


async def ai_judge_order_sensitive(
    description: str, model_runtime: ModelRuntime
) -> bool:
    """Return True when the description specifies an element position."""
    messages = [
        {"role": "system", "content": system_prompt_to_judge_order_sensitive()},
        {"role": "user", "content": order_sensitive_judge_prompt(description)},
    ]
    response = await call_generative_ai(
        messages,
        model_runtime,
        {"expectedJsonObjectResponse": True},
    )
    parsed = parse_model_response_json(
        response.get("content") or "", source="generic-object"
    )
    if not isinstance(parsed, dict):
        return False
    return bool(parsed.get("isOrderSensitive"))


async def resolve_order_sensitive(options: Optional[Dict[str, Any]]) -> bool:
    """Judge order sensitivity from cache-feature options.

    Options follow upstream `CacheFeatureOptions`: target_description (or the
    camelCase form) plus model_runtime. Judging is skipped when either is
    missing, and any failure falls back to order-insensitive xpaths.
    """
    options = options or {}
    description = options.get("target_description") or options.get("targetDescription")
    runtime = options.get("model_runtime") or options.get("modelRuntime")
    if not description or runtime is None:
        return False
    try:
        return await ai_judge_order_sensitive(str(description), runtime)
    except Exception as e:
        logger.warning(f"Failed to judge order sensitivity, assuming false: {e}")
        return False
