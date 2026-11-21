"""Task-type to config-intent mapping (upstream agent/usage-intent.ts)."""


def intent_for_task_type(task_type: str) -> str:
    """extract/boolean share the insight slot; others use their own slot."""
    return "insight" if task_type in ("extract", "boolean") else task_type
