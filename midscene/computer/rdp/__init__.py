"""RDP backend for remote Windows desktops (upstream packages/computer/src/rdp)."""

from midscene.computer.rdp.address import (
    format_rdp_host,
    format_rdp_server_address,
    normalize_rdp_connection_config,
    normalize_rdp_host,
)
from midscene.computer.rdp.backend_client import (
    UnsupportedRDPBackendClient,
    create_default_rdp_backend_client,
)
from midscene.computer.rdp.device import RDPDevice
from midscene.computer.rdp.helper_binary import (
    PLATFORM_BINARY_MAP,
    get_rdp_helper_binary_path,
)
from midscene.computer.rdp.protocol import (
    RDPBackendClient,
    RDPConnectionConfig,
    RDPConnectionInfo,
    RDPHelperRequest,
    RDPHelperResponse,
    RDPMouseButton,
    RDPMouseButtonAction,
    RDPProtocolRequest,
    RDPProtocolResponse,
    RDPScrollDirection,
    RDPSecurityProtocol,
)

__all__ = [
    "RDPDevice",
    "RDPBackendClient",
    "RDPConnectionConfig",
    "RDPConnectionInfo",
    "RDPHelperRequest",
    "RDPHelperResponse",
    "RDPMouseButton",
    "RDPMouseButtonAction",
    "RDPProtocolRequest",
    "RDPProtocolResponse",
    "RDPScrollDirection",
    "RDPSecurityProtocol",
    "UnsupportedRDPBackendClient",
    "create_default_rdp_backend_client",
    "format_rdp_host",
    "format_rdp_server_address",
    "normalize_rdp_connection_config",
    "normalize_rdp_host",
    "PLATFORM_BINARY_MAP",
    "get_rdp_helper_binary_path",
]
