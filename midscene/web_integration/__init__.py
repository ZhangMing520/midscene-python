"""
Web integration module for Midscene Python
"""

from midscene.web_integration.bridge_mode import (
    BridgeServer,
    BridgeWebPage,
    kill_running_server,
)
from midscene.web_integration.playwright import PlaywrightWebPage

__all__ = [
    "PlaywrightWebPage",
    "BridgeWebPage",
    "BridgeServer",
    "kill_running_server",
]
