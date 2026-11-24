"""Generic agent progress bus (upstream agent/progress/progress-bus.ts)."""

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

ProgressListener = Callable[[dict[str, Any]], object]


class ProgressOwner(Protocol):
    _progress_listeners: list[ProgressListener]
    _progress_sequence: int

    def remove_progress_listener(self, listener: ProgressListener) -> None: ...


class AgentProgressBus:
    """Broadcast channel that stamps a monotonic sequence per event."""

    def __init__(self) -> None:
        self._listeners: list[ProgressListener] = []
        self._sequence = 0

    def subscribe(self, listener: ProgressListener) -> Callable[[], None]:
        """Register a listener and return a disposer."""
        self._listeners.append(listener)

        def dispose() -> None:
            self.unsubscribe(listener)

        return dispose

    def unsubscribe(self, listener: ProgressListener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def clear(self) -> None:
        self._listeners.clear()

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def publish(self, scope: str, phase: str, data: Any) -> None:
        self._sequence += 1
        event = {
            "scope": scope,
            "phase": phase,
            "sequence": self._sequence,
            "data": data,
        }
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as error:  # listeners must never break execution
                logger.warning(f"error in progress listener, ignoring: {error}")


async def emit_progress(
    agent: ProgressOwner, scope: str, phase: str, data: Any
) -> None:
    """Publish one event through the agent's listener list."""
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
        except Exception as error:  # listeners must never break execution
            logger.warning(f"progress listener threw, ignoring: {error}")


def add_progress_listener(
    agent: ProgressOwner, listener: ProgressListener
) -> Callable[[], None]:
    """Subscribe to agent progress; returns a remove function."""
    agent._progress_listeners.append(listener)

    def remove() -> None:
        agent.remove_progress_listener(listener)

    return remove


def remove_progress_listener(agent: ProgressOwner, listener: ProgressListener) -> None:
    try:
        agent._progress_listeners.remove(listener)
    except ValueError:
        pass


def clear_progress_listeners(agent: ProgressOwner) -> None:
    agent._progress_listeners.clear()


__all__ = [
    "AgentProgressBus",
    "add_progress_listener",
    "clear_progress_listeners",
    "emit_progress",
    "remove_progress_listener",
]
