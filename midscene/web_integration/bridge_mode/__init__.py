"""Bridge mode over the official Midscene Chrome extension (upstream bridge-mode)."""

from midscene.web_integration.bridge_mode.agent_cli_side import (
    AgentOverChromeBridge,
    get_bridge_page_in_cli_side,
)
from midscene.web_integration.bridge_mode.io_server import (
    BridgeServer,
    kill_running_server,
)
from midscene.web_integration.bridge_mode.page_browser_side import (
    BridgeWebPage,
    ExtensionBridgePageBrowserSide,
)

__all__ = [
    "AgentOverChromeBridge",
    "BridgeWebPage",
    "BridgeServer",
    "ExtensionBridgePageBrowserSide",
    "get_bridge_page_in_cli_side",
    "kill_running_server",
]
