"""Foreground CLI stop-signal handling (upstream cli/interrupt.ts).

Keeps graceful-stop handlers installed until asynchronous artifact
finalization has completed. A second explicit Ctrl+C is the escape hatch.
"""

import asyncio
import os
import signal
import sys
from typing import Any, Dict, Optional

try:  # POSIX only
    import termios
    import tty
except ImportError:  # pragma: no cover - non-POSIX
    termios = None
    tty = None

SIGINT_EXIT_CODE = 130

_active_waiters: Dict[Any, int] = {}
_SIGNAL_NAMES = ("SIGINT", "SIGTERM", "SIGHUP")


def _waiter_key(source: Any) -> Any:
    return source if source is not None else "process"


def has_active_cli_interrupt_waiter(source: Any = None) -> bool:
    return _active_waiters.get(_waiter_key(source), 0) > 0


def _register(source: Any) -> Any:
    key = _waiter_key(source)
    _active_waiters[key] = _active_waiters.get(key, 0) + 1
    registered = True

    def unregister() -> None:
        nonlocal registered
        if not registered:
            return
        registered = False
        remaining = _active_waiters.get(key, 1) - 1
        if remaining > 0:
            _active_waiters[key] = remaining
        else:
            _active_waiters.pop(key, None)

    return unregister


class _TerminalCtrlCGuard:
    """Capture Ctrl+C as raw input while a foreground command finalizes."""

    def __init__(self, on_ctrl_c: Any) -> None:
        self._on_ctrl_c = on_ctrl_c
        self._thread: Optional[Any] = None
        self._stop = False
        self._fd: Optional[int] = None

    def install(self) -> None:
        if termios is None or not sys.stdin.isatty():
            return
        import threading

        self._fd = sys.stdin.fileno()
        try:
            self._was_raw = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:  # noqa: BLE001
            return

        def read_loop() -> None:
            while not self._stop:
                try:
                    chunk = os.read(self._fd, 1)
                except OSError:
                    return
                if not chunk:
                    return
                if chunk == b"\x03":
                    self._on_ctrl_c()

        self._thread = threading.Thread(target=read_loop, daemon=True)
        self._thread.start()

    def dispose(self) -> None:
        self._stop = True
        if self._fd is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._was_raw)
            except Exception:  # noqa: BLE001
                pass


class CliInterruptWaiter:
    """Resolves on the first stop signal or watchdog timeout."""

    def __init__(
        self,
        watchdog_ms: float,
        source: Any = None,
        input_source: Any = None,
        force_exit: Any = None,
    ) -> None:
        self._source = source
        self._loop = asyncio.get_running_loop()
        self._future: asyncio.Future = self._loop.create_future()
        self._finished = False
        self._disposed = False
        self._watchdog_handle: Optional[asyncio.TimerHandle] = None
        self._previous_handlers: Dict[int, Any] = {}
        self._unregister = _register(source)
        self._force_exit = force_exit or (lambda code: sys.exit(code))
        self._terminal = _TerminalCtrlCGuard(self._on_terminal_ctrl_c)

        try:
            for signal_name in _SIGNAL_NAMES:
                self._bind_signal(signal_name)
            if input_source is None and source is None:
                self._terminal.install()
            if watchdog_ms > 0:
                self._watchdog_handle = self._loop.call_later(
                    watchdog_ms / 1000.0, lambda: self._finish("watchdog")
                )
        except Exception:
            self.dispose()
            raise

    @property
    def result(self) -> asyncio.Future:
        return self._future

    def _bind_signal(self, signal_name: str) -> None:
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            return

        def handler(_signum: int, _frame: Any) -> None:
            self._loop.call_soon_threadsafe(
                lambda: self._finish(signal_name.lower())
            )

        try:
            self._previous_handlers[signal_value] = signal.getsignal(signal_value)
            signal.signal(signal_value, handler)
        except (ValueError, OSError):
            # Not on the main thread; keep the signal untouched.
            self._previous_handlers.pop(signal_value, None)

    def _finish(self, reason: str) -> None:
        if self._finished:
            return
        self._finished = True
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None
        if not self._future.done():
            self._future.set_result(reason)

    def _on_terminal_ctrl_c(self) -> None:
        if not self._finished:
            self._loop.call_soon_threadsafe(lambda: self._finish("sigint"))
            return
        self.dispose()
        self._force_exit(SIGINT_EXIT_CODE)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        for signal_value, previous in self._previous_handlers.items():
            try:
                signal.signal(signal_value, previous)
            except (ValueError, OSError):
                pass
        self._previous_handlers.clear()
        self._terminal.dispose()
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None
        self._unregister()


def create_cli_interrupt_waiter(
    watchdog_ms: float,
    source: Any = None,
    input_source: Any = None,
    force_exit: Any = None,
) -> CliInterruptWaiter:
    return CliInterruptWaiter(watchdog_ms, source, input_source, force_exit)


async def wait_for_cli_interrupt(
    watchdog_ms: float, source: Any = None, input: Any = None
) -> str:
    waiter = create_cli_interrupt_waiter(
        watchdog_ms, source, input_source=input
    )
    try:
        return await waiter.result
    finally:
        waiter.dispose()


__all__ = [
    "CliInterruptWaiter",
    "SIGINT_EXIT_CODE",
    "create_cli_interrupt_waiter",
    "has_active_cli_interrupt_waiter",
    "wait_for_cli_interrupt",
]
