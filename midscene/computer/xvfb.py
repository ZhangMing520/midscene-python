"""Xvfb lifecycle for headless Linux desktop automation (upstream computer/xvfb.ts).

Xvfb is only started when explicitly requested (``headless=True``); other
platforms never need it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypedDict

from loguru import logger

from midscene.shared.cli.interrupt import has_active_cli_interrupt_waiter

DEFAULT_RESOLUTION = "1920x1080x24"
DEFAULT_DISPLAY_START = 99
XVFB_LOCK_DIR = "/tmp"

_MONITOR_SCRIPT = """\
import os, signal, sys, time
parent_pid = int(sys.argv[1])
xvfb_pid = int(sys.argv[2])
while True:
    time.sleep(0.1)
    try:
        os.kill(xvfb_pid, 0)
    except OSError:
        sys.exit(0)
    try:
        os.kill(parent_pid, 0)
    except OSError:
        try:
            os.kill(xvfb_pid, signal.SIGTERM)
        except OSError:
            pass
        sys.exit(0)
"""


class XvfbOptions(TypedDict, total=False):
    resolution: str
    displayNumber: int


@dataclass
class XvfbInstance:
    process: subprocess.Popen
    display: str

    def stop(self) -> None:
        try:
            self.process.terminate()
        except OSError:
            pass


def schedule_xvfb_stop_after_process_exit(
    instance: XvfbInstance, parent_pid: Optional[int] = None
) -> subprocess.Popen:
    """Stop Xvfb only after the owning process exits.

    Killing Xvfb from the same process can make Xlib call ``exit(1)`` while
    X11 clients are still connected, so the cleanup runs in a detached monitor.
    """
    xvfb_pid = instance.process.pid
    if not xvfb_pid:
        raise RuntimeError(
            "Cannot schedule Xvfb cleanup before its process starts"
        )
    monitor = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _MONITOR_SCRIPT,
            str(parent_pid or os.getpid()),
            str(xvfb_pid),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return monitor


def create_xvfb_signal_cleanup(
    cleanup: Callable[[], None], source: object = None
) -> Callable[..., None]:
    """Return a signal handler that skips cleanup while CLI handlers run."""

    def handler(_signum: object = None, _frame: object = None) -> None:
        if not has_active_cli_interrupt_waiter(source):
            cleanup()

    return handler


def check_xvfb_installed() -> bool:
    return shutil.which("Xvfb") is not None


def _display_lock_path(display_number: int) -> str:
    return os.path.join(XVFB_LOCK_DIR, f".X{display_number}-lock")


def find_available_display(start_from: int = DEFAULT_DISPLAY_START) -> int:
    for display_number in range(start_from, start_from + 100):
        if not os.path.exists(_display_lock_path(display_number)):
            return display_number
    raise RuntimeError(
        "No available display number found "
        f"(checked {start_from} to {start_from + 99})"
    )


def start_xvfb(options: Optional[XvfbOptions] = None) -> XvfbInstance:
    """Start Xvfb and return the instance (raises when it cannot start)."""
    options = options or {}
    resolution = options.get("resolution") or DEFAULT_RESOLUTION
    display_number = options.get("displayNumber")
    if display_number is None:
        display_number = find_available_display()
    display = f":{display_number}"

    logger.debug(f"Starting Xvfb on display {display} with resolution {resolution}")
    process = subprocess.Popen(
        [
            "Xvfb",
            display,
            "-screen",
            "0",
            resolution,
            "-ac",
            "-nolisten",
            "tcp",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Xvfb has no readiness handshake; the upstream implementation also waits.
    time.sleep(0.5)
    exit_code = process.poll()
    if exit_code is not None:
        raise RuntimeError(f"Xvfb exited unexpectedly with code {exit_code}")

    return XvfbInstance(process=process, display=display)


def needs_xvfb(explicit_opt: Optional[bool] = None) -> bool:
    """Xvfb is only needed on Linux and only when explicitly requested."""
    if not sys.platform.startswith("linux"):
        return False
    return explicit_opt is True


__all__ = [
    "DEFAULT_DISPLAY_START",
    "DEFAULT_RESOLUTION",
    "XVFB_LOCK_DIR",
    "XvfbInstance",
    "XvfbOptions",
    "check_xvfb_installed",
    "create_xvfb_signal_cleanup",
    "find_available_display",
    "needs_xvfb",
    "schedule_xvfb_stop_after_process_exit",
    "start_xvfb",
]
