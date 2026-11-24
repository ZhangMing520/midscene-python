"""Per-request timeout and abort-signal helpers.

Upstream: ``ai-model/service-caller/request-timeout.ts``.
"""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any, NamedTuple, TypeVar

from midscene.shared.types import AbortError, AbortSignal

DEFAULT_AI_CALL_TIMEOUT_MS = 180_000

AI_CALL_HARD_TIMEOUT_CODE = "AI_CALL_HARD_TIMEOUT"

T = TypeVar("T")


class AIRequestTimeoutError(Exception):
    """Raised when a single AI call exceeds the hard request timeout."""

    code = AI_CALL_HARD_TIMEOUT_CODE

    def __init__(self, timeout_ms: float) -> None:
        display = (
            int(timeout_ms)
            if isinstance(timeout_ms, float) and timeout_ms.is_integer()
            else timeout_ms
        )
        super().__init__(
            f"AI call hard timeout after {display}ms (full request time exceeded)"
        )
        self.timeout_ms = timeout_ms

    @property
    def name(self) -> str:
        return "AIRequestTimeoutError"


class RequestAbortSignal(NamedTuple):
    """A composed request signal and the disposer that releases it."""

    signal: AbortSignal
    cleanup: Callable[[], None]


def resolve_effective_timeout_ms(timeout: float | None) -> float | None:
    """Per-request hard timeout in milliseconds.

    ``None`` (not configured) uses the default; ``0`` explicitly disables the
    Midscene hard timeout. Negative values are forwarded unchanged, matching
    the upstream ``return timeout === 0 ? null : timeout``.
    """
    if timeout is None:
        return float(DEFAULT_AI_CALL_TIMEOUT_MS)
    if timeout == 0:
        return None
    return float(timeout)


def is_hard_timeout_error(err: Any) -> bool:
    """True when the error (or its cause) carries the hard-timeout code."""
    if err is None:
        return False
    if getattr(err, "code", None) == AI_CALL_HARD_TIMEOUT_CODE:
        return True
    cause = getattr(err, "__cause__", None)
    return (
        cause is not None and getattr(cause, "code", None) == AI_CALL_HARD_TIMEOUT_CODE
    )


def _signal_aborted(signal: Any) -> bool:
    aborted = getattr(signal, "aborted", None)
    if aborted is not None:
        return bool(aborted)
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    return False


def _signal_reason(signal: Any) -> Any:
    return getattr(signal, "reason", None)


def _throw_if_aborted(signal: Any) -> None:
    thrower = getattr(signal, "throw_if_aborted", None)
    if callable(thrower):
        thrower()
        return
    if _signal_aborted(signal):
        reason = _signal_reason(signal)
        if isinstance(reason, BaseException):
            raise reason
        raise AbortError(
            "Operation interrupted by an external abort signal.\n"
            f"Reason: {reason or 'signal already aborted'}"
        )


def _add_abort_listener(signal: Any, callback: Callable[[], None]) -> None:
    adder = getattr(signal, "add_event_listener", None)
    if not callable(adder):
        adder = getattr(signal, "addEventListener", None)
    if not callable(adder):
        raise TypeError("signal must expose add_event_listener('abort', cb)")
    adder("abort", callback)


def _remove_abort_listener(signal: Any, callback: Callable[[], None]) -> None:
    remover = getattr(signal, "remove_event_listener", None)
    if not callable(remover):
        remover = getattr(signal, "removeEventListener", None)
    if callable(remover):
        remover("abort", callback)


def build_request_abort_signal(
    timeout_ms: float | None,
    user_signal: Any | None = None,
) -> RequestAbortSignal:
    """Compose a hard-timeout signal with the caller's cancellation signal.

    Passing ``None`` for ``timeout_ms`` disables the hard timeout and only
    forwards the user signal. The returned ``cleanup`` must be invoked once the
    request settles so the timer and listener do not outlive it.
    """
    controller = AbortSignal()

    if user_signal is not None and _signal_aborted(user_signal):
        controller.abort(_signal_reason(user_signal))
        return RequestAbortSignal(controller, lambda: None)

    timer: threading.Timer | None = None
    if timeout_ms is not None:
        timer = threading.Timer(
            timeout_ms / 1000,
            lambda: controller.abort(AIRequestTimeoutError(timeout_ms)),
        )
        timer.daemon = True
        timer.start()

    on_user_abort: Callable[[], None] | None = None
    if user_signal is not None:

        def on_user_abort() -> None:
            controller.abort(_signal_reason(user_signal))

        _add_abort_listener(user_signal, on_user_abort)

    def cleanup() -> None:
        if timer is not None:
            timer.cancel()
        if user_signal is not None and on_user_abort is not None:
            _remove_abort_listener(user_signal, on_user_abort)

    return RequestAbortSignal(controller, cleanup)


def _consume_task_exception(task: "asyncio.Future[Any]") -> None:
    if not task.cancelled():
        task.exception()


async def run_with_abort_signal(
    signal: Any,
    operation: Callable[[], Coroutine[Any, Any, T]],
) -> T:
    """Race an async operation against cancellation without cancelling it."""
    _throw_if_aborted(signal)

    loop = asyncio.get_running_loop()
    aborted: asyncio.Future[Any] = loop.create_future()

    def on_abort() -> None:
        def resolve() -> None:
            if not aborted.done():
                aborted.set_result(_signal_reason(signal))

        loop.call_soon_threadsafe(resolve)

    _add_abort_listener(signal, on_abort)
    task = asyncio.ensure_future(operation())
    try:
        done, _pending = await asyncio.wait(
            {task, aborted}, return_when=asyncio.FIRST_COMPLETED
        )
        # A request failure that wins the race keeps its original error.
        if task in done:
            return await task
        reason = aborted.result()
        if isinstance(reason, BaseException):
            raise reason
        raise AbortError(
            "Operation interrupted by an external abort signal.\n"
            f"Reason: {reason or 'signal already aborted'}"
        )
    finally:
        _remove_abort_listener(signal, on_abort)
        if not aborted.done():
            aborted.cancel()
        if not task.done():
            # The operation is abandoned on abort; retrieve its eventual
            # exception so a late failure is not reported as unhandled.
            task.add_done_callback(_consume_task_exception)


async def wait_for_retry(ms: float, signal: Any | None = None) -> None:
    """Wait between retries; aborting stops the wait without another request."""
    if signal is None:
        await asyncio.sleep(ms / 1000)
        return

    _throw_if_aborted(signal)

    loop = asyncio.get_running_loop()
    aborted: asyncio.Future[Any] = loop.create_future()

    def on_abort() -> None:
        def resolve() -> None:
            if not aborted.done():
                aborted.set_result(_signal_reason(signal))

        loop.call_soon_threadsafe(resolve)

    _add_abort_listener(signal, on_abort)
    try:
        reason = await asyncio.wait_for(aborted, timeout=ms / 1000)
    except TimeoutError:
        return
    finally:
        _remove_abort_listener(signal, on_abort)

    if isinstance(reason, BaseException):
        raise reason
    raise AbortError(
        "Operation interrupted by an external abort signal.\n"
        f"Reason: {reason or 'signal already aborted'}"
    )
