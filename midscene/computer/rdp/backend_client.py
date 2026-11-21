"""RDP backend clients (upstream backend-client.ts).

The upstream package ships a `HelperProcessRDPBackendClient` that spawns the
native helper binary. The Python SDK has no bundled helper binary yet, so the
default client keeps the upstream "not implemented" behaviour and callers can
inject a working `RDPBackendClient` into `RDPDevice`.
"""

from midscene.computer.rdp.protocol import (
    RDPBackendClient,
    RDPConnectionConfig,
    RDPConnectionInfo,
)


def _not_implemented() -> RuntimeError:
    return RuntimeError(
        "RDP backend transport is not implemented yet. Inject a custom "
        "backend into RDPDevice or implement a real helper transport."
    )


class UnsupportedRDPBackendClient:
    """Default backend: the helper transport is not implemented (upstream)."""

    async def connect(self, config: RDPConnectionConfig) -> RDPConnectionInfo:
        raise _not_implemented()

    async def disconnect(self) -> None:
        raise _not_implemented()

    async def screenshot_base64(self) -> str:
        raise _not_implemented()

    async def size(self):
        raise _not_implemented()

    async def mouse_move(self, x: int, y: int) -> None:
        raise _not_implemented()

    async def mouse_button(self, button, action) -> None:
        raise _not_implemented()

    async def wheel(self, direction, amount, x=None, y=None) -> None:
        raise _not_implemented()

    async def key_press(self, key_name: str) -> None:
        raise _not_implemented()

    async def type_text(self, text: str) -> None:
        raise _not_implemented()

    async def clear_input(self) -> None:
        raise _not_implemented()


def create_default_rdp_backend_client() -> RDPBackendClient:
    """Default backend factory (upstream createDefaultRDPBackendClient)."""
    return UnsupportedRDPBackendClient()


__all__ = [
    "UnsupportedRDPBackendClient",
    "create_default_rdp_backend_client",
]
