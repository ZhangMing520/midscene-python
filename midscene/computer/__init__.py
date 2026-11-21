"""Computer automation (upstream packages/computer)."""

from midscene.computer.device import ComputerDevice
from midscene.computer.agent import ComputerAgent
from midscene.computer.rdp import (
    RDPBackendClient,
    RDPDevice,
    UnsupportedRDPBackendClient,
)

__all__ = [
    "ComputerDevice",
    "ComputerAgent",
    "RDPDevice",
    "RDPBackendClient",
    "UnsupportedRDPBackendClient",
]
