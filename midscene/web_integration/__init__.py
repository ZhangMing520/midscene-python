"""
Web integration module for Midscene Python
"""

from midscene.web_integration.selenium_page import SeleniumWebPage
from midscene.web_integration.playwright_page import PlaywrightWebPage
from midscene.web_integration.bridge import BridgeWebPage, BridgeServer, kill_running_server

__all__ = [
    "SeleniumWebPage",
    "PlaywrightWebPage",
    "BridgeWebPage",
    "BridgeServer",
    "kill_running_server",
]