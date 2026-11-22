"""Computer automation (upstream packages/computer)."""

from midscene.computer.device import ComputerDevice
from midscene.computer.agent import (
    ComputerAgent,
    agent_for_computer,
    agent_for_rdp_computer,
    agent_from_computer,
)
from midscene.computer.rdp import (
    HelperProcessRDPBackendClient,
    RDPBackendClient,
    RDPDevice,
    UnsupportedRDPBackendClient,
    create_default_rdp_backend_client,
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
    "agent_for_computer",
    "agent_for_rdp_computer",
    "agent_from_computer",
    "RDPDevice",
    "RDPBackendClient",
    "UnsupportedRDPBackendClient",
    "HelperProcessRDPBackendClient",
    "create_default_rdp_backend_client",
    "XvfbInstance",
    "XvfbOptions",
    "check_xvfb_installed",
    "create_xvfb_signal_cleanup",
    "find_available_display",
    "needs_xvfb",
    "schedule_xvfb_stop_after_process_exit",
    "start_xvfb",
]
