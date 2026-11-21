"""RDP device for remote Windows desktops (upstream rdp/device.ts).

The device speaks the JSON request/response protocol from `protocol.py`
through an injectable backend. The default backend raises the upstream
not-implemented error until a real helper transport is provided.
"""

from typing import List, Optional

from loguru import logger

from midscene.computer.rdp.backend_client import (
    UnsupportedRDPBackendClient,
)
from midscene.computer.rdp.protocol import (
    RDPBackendClient,
    RDPConnectionConfig,
    RDPConnectionInfo,
)
from midscene.core.types import (
    AbstractInterface,
    InterfaceType,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)


class RDPDevice(AbstractInterface):
    """Remote-desktop device delegating to an injectable RDP backend."""

    def __init__(
        self,
        config: RDPConnectionConfig,
        backend: Optional[RDPBackendClient] = None,
    ):
        self.config = config
        self.backend: RDPBackendClient = backend or UnsupportedRDPBackendClient()
        self._connection_info: Optional[RDPConnectionInfo] = None

    @property
    def interface_type(self) -> InterfaceType:
        return InterfaceType.COMPUTER

    async def connect(self) -> None:
        self._connection_info = await self.backend.connect(self.config)
        logger.info(f"RDP connected: {self._connection_info}")

    async def disconnect(self) -> None:
        await self.backend.disconnect()
        self._connection_info = None

    async def get_context(self) -> UIContext:
        screenshot = await self.backend.screenshot_base64()
        size = await self.backend.size()
        return UIContext(
            screenshot_base64=screenshot,
            size=Size(width=int(size["width"]), height=int(size["height"])),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root",
                    content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0),
                    node_type=NodeType.CONTAINER,
                )
            ),
        )

    async def action_space(self) -> List[str]:
        return [
            "tap",
            "input",
            "key_press",
            "scroll",
            "double_click",
            "right_click",
        ]

    async def tap(self, x: float, y: float) -> None:
        await self.backend.mouse_move(int(x), int(y))
        await self.backend.mouse_button("left", "click")

    async def right_click(self, x: float, y: float) -> None:
        await self.backend.mouse_move(int(x), int(y))
        await self.backend.mouse_button("right", "click")

    async def double_click(self, x: float, y: float) -> None:
        await self.backend.mouse_move(int(x), int(y))
        await self.backend.mouse_button("left", "doubleClick")

    async def input_text(self, text: str) -> None:
        await self.backend.type_text(text)

    async def keyboard_press(self, key: str) -> None:
        await self.backend.key_press(key)

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        await self.backend.wheel(direction, distance or 500)

    async def hover(self, x: float, y: float) -> None:
        await self.backend.mouse_move(int(x), int(y))


__all__ = ["RDPDevice"]
