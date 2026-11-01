"""RDP device for remote Windows desktops.

Synced from upstream packages/computer/src/rdp (v1.17.4). The device speaks
a JSON request/response protocol (protocol.ts) through a per-platform
`rdp-helper` binary. The upstream transport itself is intentionally
unimplemented — the same injectable-backend design is ported here: pass a
custom `backend` implementing RDPBackendClient, or the default client
raises the upstream not-implemented error.
"""

import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from loguru import logger

from ..core.types import (
    AbstractInterface,
    InterfaceType,
    Rect,
    Size,
    UIContext,
    UITree,
    UINode,
    NodeType,
)

PLATFORM_BINARY_MAP = {
    "Darwin": ("darwin", "rdp-helper"),
    "Linux": ("linux", "rdp-helper"),
    "Windows": ("win32", "rdp-helper.exe"),
}


def get_rdp_helper_binary_path(package_root: Optional[str] = None) -> str:
    """Locate the per-platform rdp-helper binary (upstream helper-binary.ts)."""
    system = platform.system()
    mapping = PLATFORM_BINARY_MAP.get(system)
    if not mapping:
        raise RuntimeError(
            f"@midscene/computer RDP helper does not support platform {system}"
        )
    directory, file_name = mapping
    root = Path(package_root) if package_root else Path(__file__).parent
    for candidate in (root / ".." / "bin" / directory / file_name,
                      root / "bin" / directory / file_name):
        candidate = candidate.resolve()
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        f"rdp-helper binary not found for {system}; expected at "
        f"{(root / 'bin' / directory / file_name).resolve()}"
    )


class RDPBackendClient(Protocol):
    """Injectable transport behind RDPDevice (upstream RDPBackendClient)."""

    async def connect(self, config: Dict[str, Any]) -> Dict[str, Any]: ...

    async def disconnect(self) -> None: ...

    async def screenshot_base64(self) -> str: ...

    async def size(self) -> Dict[str, Any]: ...

    async def mouse_move(self, x: int, y: int) -> None: ...

    async def mouse_button(self, button: str, action: str) -> None: ...

    async def wheel(self, direction: str, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> None: ...

    async def key_press(self, key_name: str) -> None: ...

    async def type_text(self, text: str) -> None: ...


class UnsupportedRDPBackendClient:
    """Default backend: the transport is not implemented (same as upstream)."""

    @staticmethod
    def _not_implemented():
        return RuntimeError(
            "RDP backend transport is not implemented yet. Inject a custom "
            "backend into RDPDevice or implement a real helper transport."
        )

    async def connect(self, config): raise self._not_implemented()
    async def disconnect(self): raise self._not_implemented()
    async def screenshot_base64(self): raise self._not_implemented()
    async def size(self): raise self._not_implemented()
    async def mouse_move(self, x, y): raise self._not_implemented()
    async def mouse_button(self, button, action): raise self._not_implemented()
    async def wheel(self, direction, amount, x=None, y=None): raise self._not_implemented()
    async def key_press(self, key_name): raise self._not_implemented()
    async def type_text(self, text): raise self._not_implemented()


class RDPDevice(AbstractInterface):
    """Remote-desktop device delegating to an injectable RDP backend."""

    def __init__(self, config: Dict[str, Any], backend: Optional[RDPBackendClient] = None):
        self.config = config
        self.backend: RDPBackendClient = backend or UnsupportedRDPBackendClient()
        self._connection_info: Optional[Dict[str, Any]] = None

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
                    id="root", content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0), node_type=NodeType.CONTAINER,
                )
            ),
        )

    async def action_space(self) -> List[str]:
        return ["tap", "input", "key_press", "scroll", "double_click", "right_click"]

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
