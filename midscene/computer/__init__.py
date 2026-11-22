"""Computer automation (upstream packages/computer)."""

from midscene.computer.device import ComputerDevice
from midscene.computer.agent import ComputerAgent
from midscene.computer.rdp import (
    RDPBackendClient,
    RDPDevice,
    UnsupportedRDPBackendClient,
)
from midscene.computer.xvfb import (
    XvfbInstance,
    XvfbOptions,
    check_xvfb_installed,
    create_xvfb_signal_cleanup,
    find_available_display,
    needs_xvfb,
    schedule_xvfb_stop_after_process_exit,
    start_xvfb,
)

__all__ = [
    "ComputerDevice",
    "ComputerAgent",
    "RDPDevice",
    "RDPBackendClient",
    "UnsupportedRDPBackendClient",
    "XvfbInstance",
    "XvfbOptions",
    "check_xvfb_installed",
    "create_xvfb_signal_cleanup",
    "find_available_display",
    "needs_xvfb",
    "schedule_xvfb_stop_after_process_exit",
    "start_xvfb",
]
