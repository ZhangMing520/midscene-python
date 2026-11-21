"""
Web integration module for Midscene Python
"""

from midscene.web_integration.playwright import PlaywrightWebPage
from midscene.web_integration.bridge_mode import (
    BridgeServer,
    BridgeWebPage,
    kill_running_server,
)

__all__ = [
    "PlaywrightWebPage",
    "BridgeWebPage",
    "BridgeServer",
    "kill_running_server",
]
