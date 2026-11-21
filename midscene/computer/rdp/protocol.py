"""JSON request/response protocol for the RDP helper (upstream protocol.ts)."""

from typing import Any, Dict, Literal, Optional, Protocol, TypedDict

from midscene.core.types import Size

RDPMouseButton = Literal["left", "right", "middle"]
RDPMouseButtonAction = Literal["down", "up", "click", "doubleClick"]
RDPScrollDirection = Literal["up", "down", "left", "right"]
RDPSecurityProtocol = Literal["auto", "tls", "nla", "rdp"]


class RDPConnectionConfig(TypedDict, total=False):
    """Connection settings for an RDP session (upstream RDPConnectionConfig)."""

    host: str
    port: int
    username: str
    password: str
    domain: str
    localAddress: str
    adminSession: bool
    ignoreCertificate: bool
    securityProtocol: RDPSecurityProtocol
    desktopWidth: int
    desktopHeight: int


class RDPConnectionInfo(TypedDict):
    """Information returned once the helper is connected."""

    sessionId: str
    size: Dict[str, Any]
    server: str


class RDPHelperEnvelope(TypedDict):
    id: str
    payload: Dict[str, Any]


RDPProtocolRequest = Dict[str, Any]
RDPProtocolResponse = Dict[str, Any]
RDPHelperRequest = Dict[str, Any]
RDPHelperResponse = Dict[str, Any]


class RDPBackendClient(Protocol):
    """Injectable transport behind RDPDevice (upstream RDPBackendClient)."""

    async def connect(self, config: RDPConnectionConfig) -> RDPConnectionInfo: ...

    async def disconnect(self) -> None: ...

    async def screenshot_base64(self) -> str: ...

    async def size(self) -> Size: ...

    async def mouse_move(self, x: int, y: int) -> None: ...

    async def mouse_button(
        self, button: RDPMouseButton, action: RDPMouseButtonAction
    ) -> None: ...

    async def wheel(
        self,
        direction: RDPScrollDirection,
        amount: int,
        x: Optional[int] = None,
        y: Optional[int] = None,
    ) -> None: ...

    async def key_press(self, key_name: str) -> None: ...

    async def type_text(self, text: str) -> None: ...

    async def clear_input(self) -> None: ...


__all__ = [
    "RDPMouseButton",
    "RDPMouseButtonAction",
    "RDPScrollDirection",
    "RDPSecurityProtocol",
    "RDPConnectionConfig",
    "RDPConnectionInfo",
    "RDPHelperEnvelope",
    "RDPProtocolRequest",
    "RDPProtocolResponse",
    "RDPHelperRequest",
    "RDPHelperResponse",
    "RDPBackendClient",
]
