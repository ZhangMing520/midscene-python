"""Synced from upstream packages/computer/tests/unit-test/xvfb.test.ts.

The upstream suite mocks ``node:fs``/``node:child_process`` and a Node
``EventEmitter``. The Python port mocks ``os.path.exists`` / ``shutil.which``
and drives Python signal handlers (or ``has_active_cli_interrupt_waiter``)
instead.
"""

import asyncio
import signal
from unittest.mock import Mock

import pytest

from midscene.computer import xvfb
from midscene.shared.cli.interrupt import (
    create_cli_interrupt_waiter,
    wait_for_cli_interrupt,
)


def test_should_return_false_on_non_linux_platforms(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.sys, "platform", "darwin")
    assert xvfb.needs_xvfb(True) is False


def test_should_return_false_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.sys, "platform", "win32")
    assert xvfb.needs_xvfb(True) is False


def test_should_return_true_on_linux_with_explicit_true(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.sys, "platform", "linux")
    assert xvfb.needs_xvfb(True) is True


def test_should_return_false_on_linux_with_explicit_false(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.sys, "platform", "linux")
    assert xvfb.needs_xvfb(False) is False


def test_should_return_false_on_linux_without_explicit_option(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.sys, "platform", "linux")
    assert xvfb.needs_xvfb() is False
    assert xvfb.needs_xvfb(None) is False


def test_should_return_startfrom_when_no_lock_files_exist(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.os.path, "exists", lambda _path: False)
    assert xvfb.find_available_display(99) == 99


def test_should_skip_occupied_display_numbers(monkeypatch) -> None:
    responses = iter([True, True, False])  # :99 and :100 occupied, :101 free
    monkeypatch.setattr(xvfb.os.path, "exists", lambda _path: next(responses))
    assert xvfb.find_available_display(99) == 101


def test_should_throw_if_no_display_is_available(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.os.path, "exists", lambda _path: True)
    with pytest.raises(RuntimeError, match="No available display number found"):
        xvfb.find_available_display(99)


def test_should_return_false_when_xvfb_is_not_installed(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.shutil, "which", lambda _name: None)
    assert xvfb.check_xvfb_installed() is False


def test_should_return_true_when_xvfb_is_installed(monkeypatch) -> None:
    monkeypatch.setattr(xvfb.shutil, "which", lambda _name: "/usr/bin/Xvfb")
    assert xvfb.check_xvfb_installed() is True


@pytest.mark.skip(
    reason=(
        "Node.js child_process .unref() has no Python equivalent; the port "
        "detaches the monitor with start_new_session instead"
    )
)
def test_unrefs_xvfb_and_a_detached_process_exit_monitor() -> None:
    pass


def test_cleans_up_when_the_host_only_has_unrelated_sigint_listeners() -> None:
    cleanup = Mock()
    source = object()
    # Without a CLI interrupt waiter registered for the source, an unrelated
    # host listener must not suppress Xvfb cleanup.
    handler = xvfb.create_xvfb_signal_cleanup(cleanup, source)

    handler(None, None)

    cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_defers_cleanup_while_a_foreground_recorder_is_handling_sigint() -> None:
    cleanup = Mock()
    source = object()
    handler = xvfb.create_xvfb_signal_cleanup(cleanup, source)
    stopped = asyncio.create_task(wait_for_cli_interrupt(0, source))
    await asyncio.sleep(0)  # let the waiter register for the source
    try:
        handler(None, None)
        cleanup.assert_not_called()

        # Deliver SIGINT through the Python handler installed by the waiter.
        sigint_handler = signal.getsignal(signal.SIGINT)
        assert callable(sigint_handler)
        sigint_handler(signal.SIGINT, None)

        assert await stopped == "sigint"
        handler(None, None)
        cleanup.assert_called_once()
    finally:
        if not stopped.done():
            stopped.cancel()
        await asyncio.gather(stopped, return_exceptions=True)


@pytest.mark.asyncio
async def test_keeps_xvfb_alive_through_a_forwarded_sigterm_while_saving() -> None:
    cleanup = Mock()
    source = object()
    signal_cleanup = xvfb.create_xvfb_signal_cleanup(cleanup, source)
    waiter = create_cli_interrupt_waiter(0, source=source)
    try:
        # First SIGINT is handled by the foreground recorder.
        sigint_handler = signal.getsignal(signal.SIGINT)
        assert callable(sigint_handler)
        sigint_handler(signal.SIGINT, None)
        assert await waiter.result == "sigint"

        # A forwarded SIGTERM must keep Xvfb alive while the waiter is active.
        signal_cleanup(None, None)
        cleanup.assert_not_called()

        waiter.dispose()
        signal_cleanup(None, None)
        cleanup.assert_called_once()
    finally:
        waiter.dispose()
