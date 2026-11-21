"""Agent progress bus (upstream agent/progress/*)."""

import asyncio
from typing import Any, Callable

from loguru import logger

async def emit_progress(
    agent, scope: str, phase: str, data: Any
) -> None:
    if not agent._progress_listeners:
        return
    agent._progress_sequence += 1
    event = {
        "scope": scope,
        "phase": phase,
        "sequence": agent._progress_sequence,
        "data": data,
    }
    for listener in list(agent._progress_listeners):
        try:
            result = listener(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # listeners must never break execution
            logger.warning(f"progress listener threw, ignoring: {e}")


def add_progress_listener(agent, listener: Callable) -> Callable[[], None]:
    """Subscribe to agent progress; returns a remove function."""
    agent._progress_listeners.append(listener)

    def remove() -> None:
        agent.remove_progress_listener(listener)

    return remove


def remove_progress_listener(agent, listener: Callable) -> None:
    try:
        agent._progress_listeners.remove(listener)
    except ValueError:
        pass


def clear_progress_listeners(agent, ) -> None:
    agent._progress_listeners.clear()
