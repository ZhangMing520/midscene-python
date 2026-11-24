"""Bounded environment setup (upstream engine/setup-timeout.ts)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from midscene.core.test_runner.engine._abort import (
    abort_reason,
    add_abort_listener,
    throw_if_aborted,
)
from midscene.core.test_runner.engine.resource_operations import (
    anonymous_resource,
    track_resource_operation,
)
from midscene.core.test_runner.errors import WorkflowError

T = TypeVar("T")


async def run_setup_with_timeout(
    setup: Callable[[], Awaitable[T]],
    signal: Any,
    abort: Callable[[Any], None],
    timeout_ms: float | None = None,
) -> T:
    """Keep tracking a timed-out acquisition until it actually settles."""
    if timeout_ms is None:
        return await setup()
    throw_if_aborted(signal)

    loop = asyncio.get_event_loop()
    operation = asyncio.ensure_future(setup())
    track_resource_operation(anonymous_resource(), operation, signal, "acquisition")

    stopped: asyncio.Future[Any] = loop.create_future()

    def on_abort() -> None:
        if not stopped.done():
            stopped.set_result(abort_reason(signal))

    disposer = add_abort_listener(signal, on_abort)

    def on_timeout() -> None:
        error = WorkflowError(
            f"Environment setup timed out after {timeout_ms}ms.",
            {"code": "SETUP_TIMEOUT", "details": {"timeoutMs": timeout_ms}},
        )
        abort(error)

    timer = loop.call_later(timeout_ms / 1000.0, on_timeout)
    try:
        done, _pending = await asyncio.wait(
            {operation, stopped}, return_when=asyncio.FIRST_COMPLETED
        )
        if stopped in done:
            reason = stopped.result() if not stopped.cancelled() else None
            if isinstance(reason, BaseException):
                raise reason
            throw_if_aborted(signal)
            raise WorkflowError(
                "Environment setup aborted.",
                {"code": "SETUP_ABORTED", "cause": reason},
            )
        return operation.result()
    finally:
        timer.cancel()
        disposer()
        if not stopped.done():
            stopped.cancel()


__all__ = ["run_setup_with_timeout"]
