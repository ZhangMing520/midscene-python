"""JSON request/response protocol for the RDP helper (upstream protocol.ts)."""

from typing import Any, Literal, Protocol, TypedDict

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
    size: dict[str, Any]
    server: str


class RDPHelperEnvelope(TypedDict):
    id: str
    payload: dict[str, Any]


RDPProtocolRequest = dict[str, Any]
RDPProtocolResponse = dict[str, Any]
RDPHelperRequest = dict[str, Any]
RDPHelperResponse = dict[str, Any]


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
        x: int | None = None,
        y: int | None = None,
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
