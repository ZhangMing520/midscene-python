"""Action readiness callback (upstream agent/action-readiness.ts)."""

import asyncio
import time
from typing import Any, Dict

from loguru import logger

ACTION_READINESS_ERROR_CODE = "ACTION_READINESS_FAILED"


class ActionReadinessError(RuntimeError):
    """Wrapper marking a waitForActionReady callback failure."""

    code = ACTION_READINESS_ERROR_CODE

    def __init__(self, phase: str, action_name: Any, cause: Any) -> None:
        super().__init__(
            f"waitForActionReady {phase} failed for {action_name}: {cause}"
        )
        self.name = "ActionReadinessError"
        self.cause = cause


def is_action_readiness_error(error: Any) -> bool:
    """Recognize an ActionReadinessError, including a bounded cause chain."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, "code", None) == ACTION_READINESS_ERROR_CODE:
            return True
        error = getattr(error, "cause", None)
    return False


async def wait_for_action_ready(options: Any, action: Dict[str, Any]) -> None:
    """Await the user's waitForActionReady callback after a successful action.

    Slow waits only warn; callback failures surface as ActionReadinessError.
    """
    callback = getattr(options, "wait_for_action_ready", None)
    if not callback:
        return
    started = time.time()
    warned = False
    task = asyncio.ensure_future(
        callback({"action": {"name": action.get("type"), "id": None}})
    )
    while not task.done():
        await asyncio.sleep(0.05)
        if not warned and time.time() - started > 5:
            logger.warning(
                f"waitForActionReady for {action.get('type')} is still "
                "pending after 5000ms; continuing to wait."
            )
            warned = True
    try:
        await task
    except Exception as e:
        raise ActionReadinessError("wait", action.get("type"), e) from e


__all__ = [
    "ACTION_READINESS_ERROR_CODE",
    "ActionReadinessError",
    "is_action_readiness_error",
    "wait_for_action_ready",
]

