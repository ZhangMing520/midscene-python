"""Action readiness callback (upstream agent/action-readiness.ts)."""

import asyncio
import time
from typing import Any, Dict

from loguru import logger


async def wait_for_action_ready(options: Any, action: Dict[str, Any]) -> None:
    """Await the user's waitForActionReady callback after a successful action.

    Slow waits only warn; callback failures surface as RuntimeError.
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
        raise RuntimeError(
            f"waitForActionReady failed for {action.get('type')}: {e}"
        ) from e
