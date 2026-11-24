"""AbortSignal helpers shared by the workflow engine.

The upstream engine relies on DOM `AbortSignal` semantics
(`aborted`/`reason`/`addEventListener`). The Python SDK exposes
:class:`midscene.core.types.AbortSignal` and also accepts `asyncio.Event` /
`threading.Event`; this module normalises both shapes for the engine.
"""

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from midscene.core.types import AbortError, AbortSignal

_POLL_INTERVAL_SECONDS = 0.05


def is_aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if isinstance(signal, AbortSignal):
        return signal.aborted
    aborted = getattr(signal, "aborted", None)
    if aborted is not None:
        return bool(aborted)
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    raise TypeError("signal must be an AbortSignal, asyncio.Event or threading.Event")


def abort_reason(signal: Any) -> Any:
    return getattr(signal, "reason", None)


def throw_if_aborted(signal: Any) -> None:
    if not is_aborted(signal):
        return
    thrower = getattr(signal, "throw_if_aborted", None)
    if callable(thrower):
        thrower()
        return
    reason = abort_reason(signal) or "signal already aborted"
    raise AbortError(
        f"Operation interrupted by an external abort signal.\nReason: {reason}"
    )


def new_signal() -> AbortSignal:
    return AbortSignal()


def add_abort_listener(signal: Any, callback: Callable[[], None]) -> Callable[[], None]:
    """Register `callback` for cancellation; returns a disposer.

    `AbortSignal` listeners fire synchronously from `abort()`. Event objects
    are polled from the running event loop, which keeps engine callbacks on a
    single thread.
    """

    if isinstance(signal, AbortSignal):
        signal.add_event_listener("abort", callback)
        return lambda: signal.remove_event_listener("abort", callback)

    if hasattr(signal, "add_event_listener") and callable(signal.add_event_listener):
        signal.add_event_listener("abort", callback)
        return lambda: signal.remove_event_listener("abort", callback)

    if is_aborted(signal):
        callback()
        return lambda: None

    loop = asyncio.get_event_loop()
    task = loop.create_task(_poll_abort(signal, callback))

    def _dispose() -> None:
        if not task.done():
            task.cancel()

    return _dispose


async def _poll_abort(signal: Any, callback: Callable[[], None]) -> None:
    while not is_aborted(signal):
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    callback()


def link_abort(signal: AbortSignal, parent: Any) -> Callable[[], None]:
    """Forward cancellation from `parent` to `signal`; returns a disposer."""
    if parent is None or parent is signal:
        return lambda: None
    if is_aborted(parent):
        signal.abort(abort_reason(parent))
        return lambda: None
    return add_abort_listener(
        signal=parent, callback=lambda: signal.abort(abort_reason(parent))
    )


def abort_controller(signal: AbortSignal, reason: Any = None) -> None:
    signal.abort(reason)


def current_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_event_loop()


class AbortController:
    """Minimal upstream-compatible abort controller."""

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: Any = None) -> None:
        self.signal.abort(reason)


def sleep_zero() -> Any:
    """Yield control once, mirroring a JS microtask hop."""
    return asyncio.sleep(0)


def is_event_signal(signal: Any) -> bool:
    return hasattr(signal, "is_set") and callable(signal.is_set)


def event_waiter(signal: Any) -> Any | None:
    waiter = getattr(signal, "wait", None)
    if callable(waiter):
        return waiter
    return None


def thread_event_wait(signal: Any, timeout: float | None = None) -> bool:
    waiter = event_waiter(signal)
    if waiter is None:
        return is_aborted(signal)
    return bool(waiter(timeout))


def daemon_thread(target: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread
