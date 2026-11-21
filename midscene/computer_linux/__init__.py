"""Linux-specific re-export of midscene.computer.

Mirrors upstream @midscene/computer-linux, which re-exports the shared
computer package unchanged.
"""

from midscene.computer import (
    ComputerAgent,
    ComputerDevice,
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
