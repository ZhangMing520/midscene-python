"""Model adapters (upstream packages/core/src/ai-model/models)."""

from midscene.core.ai_model.models.model_fallback import (
    resolve_model_for_task_type,
)
from midscene.core.ai_model.models.registry import (
    ModelAdapter,
    ModelRuntime,
    get_model_adapter,
    get_model_runtime,
    is_locate_intent,
)

__all__ = [
    "ModelAdapter",
    "ModelRuntime",
    "get_model_adapter",
    "get_model_runtime",
    "is_locate_intent",
    "resolve_model_for_task_type",
]
