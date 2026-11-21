"""Bridge mode over the official Midscene Chrome extension (upstream bridge-mode)."""

from midscene.web_integration.bridge_mode.page import BridgeWebPage
from midscene.web_integration.bridge_mode.io_server import (
    BridgeServer,
    kill_running_server,
)

__all__ = ["BridgeWebPage", "BridgeServer", "kill_running_server"]
