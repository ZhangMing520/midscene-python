"""Task-type to config-intent mapping (upstream agent/usage-intent.ts)."""

from typing import Any

from loguru import logger


def intent_for_task_type(task_type: str) -> str:
    """extract/boolean share the insight slot; others use their own slot."""
    return "insight" if task_type in ("extract", "boolean") else task_type


def with_usage_intent(
    usage: dict[str, Any] | None,
    intent: str,
) -> dict[str, Any] | None:
    """Attach an intent to a usage record without overwriting an existing one."""
    if not usage:
        return None
    if usage.get("intent"):
        logger.warning(
            f'intent is already set to "{usage["intent"]}", skipping '
            f'overwrite to "{intent}"'
        )
        return usage
    return {**usage, "intent": intent}


__all__ = ["intent_for_task_type", "with_usage_intent"]
