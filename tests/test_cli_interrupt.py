"""Foreground CLI interrupt handling (upstream cli-interrupt.test.ts)."""

import asyncio
import os
import signal

import pytest

from midscene.shared.cli.interrupt import (
    create_cli_interrupt_waiter,
    has_active_cli_interrupt_waiter,
    wait_for_cli_interrupt,
)


async def _deliver(sig: int) -> None:
    os.kill(os.getpid(), sig)
    await asyncio.sleep(0.05)


class TestWaitForCliInterrupt:
    @pytest.mark.asyncio
    async def test_resolves_on_sigint_and_removes_its_listener(self):
        source = object()
        stopped = asyncio.create_task(wait_for_cli_interrupt(0, source))
        await asyncio.sleep(0)

        assert has_active_cli_interrupt_waiter(source) is True
        await _deliver(signal.SIGINT)

        assert await stopped == "sigint"
        assert has_active_cli_interrupt_waiter(source) is False

    @pytest.mark.asyncio
    async def test_uses_the_watchdog_to_finalize_a_forgotten_recording(self):
        source = object()
        stopped = await wait_for_cli_interrupt(10, source)

        assert stopped == "watchdog"
        assert has_active_cli_interrupt_waiter(source) is False

    @pytest.mark.asyncio
    async def test_keeps_termination_signals_guarded_until_saving_finishes(self):
        source = object()
        waiter = create_cli_interrupt_waiter(0, source)

        try:
            await _deliver(signal.SIGINT)
            assert await waiter.result == "sigint"

            assert has_active_cli_interrupt_waiter(source) is True

            # Package runners may forward SIGTERM after the terminal's SIGINT
            # and trigger SIGHUP when the parent exits. Both must be absorbed
            # while the recorder is still saving.
            await _deliver(signal.SIGTERM)
            await _deliver(signal.SIGHUP)
            assert has_active_cli_interrupt_waiter(source) is True
        finally:
            waiter.dispose()

        assert has_active_cli_interrupt_waiter(source) is False

    @pytest.mark.asyncio
    async def test_gracefully_stops_on_sigterm(self):
        source = object()
        stopped = asyncio.create_task(wait_for_cli_interrupt(0, source))
        await asyncio.sleep(0)
        await _deliver(signal.SIGTERM)

        assert await stopped == "sigterm"
        assert has_active_cli_interrupt_waiter(source) is False

    @pytest.mark.asyncio
    async def test_gracefully_stops_on_sighup(self):
        source = object()
        stopped = asyncio.create_task(wait_for_cli_interrupt(0, source))
        await asyncio.sleep(0)
        await _deliver(signal.SIGHUP)

        assert await stopped == "sighup"
        assert has_active_cli_interrupt_waiter(source) is False

    @pytest.mark.skip(
        reason="Python captures terminal Ctrl+C via termios on the process stdin, "
        "not an injectable input stream"
    )
    def test_captures_terminal_ctrl_c_as_input_until_saving_finishes(self):
        pass

    @pytest.mark.skip(
        reason="Python captures terminal Ctrl+C via termios on the process stdin, "
        "not an injectable input stream"
    )
    def test_releases_the_terminal_guard_on_a_second_ctrl_c_during_finalization(self):
        pass

    @pytest.mark.skip(
        reason="Python captures terminal Ctrl+C via termios on the process stdin, "
        "not an injectable input stream"
    )
    def test_restores_the_terminal_when_input_listener_setup_fails(self):
        pass

    def test_does_not_treat_unrelated_sigint_listeners_as_cli_waiters(self):
        source = object()
        previous = signal.getsignal(signal.SIGINT)

        def unrelated(_signum, _frame):
            return None

        signal.signal(signal.SIGINT, unrelated)
        try:
            assert has_active_cli_interrupt_waiter(source) is False
        finally:
            signal.signal(signal.SIGINT, previous)
