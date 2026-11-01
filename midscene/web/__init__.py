"""
Web integration module for Midscene Python
"""

from .selenium_page import SeleniumWebPage
from .playwright_page import PlaywrightWebPage
from .bridge import BridgeWebPage, BridgeServer, kill_running_server

__all__ = [
    "SeleniumWebPage",
    "PlaywrightWebPage",
    "BridgeWebPage",
    "BridgeServer",
    "kill_running_server",
]