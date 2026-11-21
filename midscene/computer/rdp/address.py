"""RDP host/address helpers (upstream address.ts)."""

from typing import Any, Dict

from midscene.computer.rdp.protocol import RDPConnectionConfig


def normalize_rdp_host(host: str) -> str:
    """Strip IPv6 brackets and surrounding whitespace (upstream)."""
    trimmed = host.strip()
    if (
        len(trimmed) >= 2
        and trimmed.startswith("[")
        and trimmed.endswith("]")
        and ":" in trimmed
    ):
        return trimmed[1:-1]
    return trimmed


def format_rdp_host(host: str) -> str:
    """Bracket a bare IPv6 host so it is unambiguous in a server string."""
    normalized_host = normalize_rdp_host(host)
    return f"[{normalized_host}]" if ":" in normalized_host else normalized_host


def format_rdp_server_address(host: str, port: int) -> str:
    return f"{format_rdp_host(host)}:{port}"


def normalize_rdp_connection_config(
    config: RDPConnectionConfig,
) -> Dict[str, Any]:
    """Normalize the host/local address before handing it to the backend."""
    normalized: Dict[str, Any] = dict(config)
    normalized["host"] = normalize_rdp_host(config["host"])
    if config.get("localAddress"):
        normalized["localAddress"] = config["localAddress"].strip()
    return normalized


__all__ = [
    "normalize_rdp_host",
    "format_rdp_host",
    "format_rdp_server_address",
    "normalize_rdp_connection_config",
]
