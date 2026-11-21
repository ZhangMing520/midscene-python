"""Task-type model fallback resolution (upstream ai-model/models/model-fallback.ts)."""

from typing import Any, Callable, Dict

from loguru import logger

from midscene.core.ai_model.models.registry import (
    ModelRuntime,
    get_model_runtime,
)

def resolve_model_for_task_type(
    get_model_config: Callable[[str], Dict[str, Any]],
    intent: str,
    task_type: str,
) -> ModelRuntime:
    """Resolve the runtime for a task type, falling back to the default model
    when the requested slot's adapter cannot perform the task."""
    requested = get_model_runtime(get_model_config(intent))
    allowed = requested.adapter.allowed_task_types
    if allowed is None or task_type in allowed:
        return requested

    runtime = get_model_runtime({**get_model_config("default"), "intent": intent})
    default_allowed = runtime.adapter.allowed_task_types
    if default_allowed is not None and task_type not in default_allowed:
        raise ValueError(
            f"The default model cannot perform {task_type}. Configure a "
            "general-purpose default model."
        )
    reason = (
        f"{requested.config.get('modelFamily')} does not support {task_type}; "
        "using the default model"
    )
    logger.warning(reason)
    runtime.model_fallback = {
        "requestedModel": requested.config.get("modelName"),
        "requestedSlot": requested.config.get("slot"),
        "taskType": task_type,
        "reason": reason,
    }
    return runtime
