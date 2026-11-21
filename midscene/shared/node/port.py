"""Port helpers (upstream packages/shared/src/node/port.ts)."""

import socket
from typing import Final

DEFAULT_PORT_SEARCH_ATTEMPTS: Final = 15


async def is_port_available(port: int) -> bool:
    """Check whether `port` can be bound on the IPv4 wildcard address.

    The playground/scrcpy servers bind ``0.0.0.0``; probing the same address
    avoids concluding a port is free when only IPv6 is available.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        server.close()


async def find_available_port(
    start_port: int, max_attempts: int = DEFAULT_PORT_SEARCH_ATTEMPTS
) -> int:
    """Find a free port starting at `start_port`."""
    port = start_port
    attempts = 0
    while not await is_port_available(port):
        attempts += 1
        if attempts >= max_attempts:
            raise RuntimeError(
                f"Unable to find available port after {max_attempts} "
                f"attempts starting from {start_port}"
            )
        port += 1
    return port


__all__ = ["find_available_port", "is_port_available"]
