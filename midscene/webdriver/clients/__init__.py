"""WebDriver clients (upstream packages/webdriver/src/clients)."""

from midscene.webdriver.clients.types import (
    DeviceInfo,
    Point,
    Size,
    WDAElement,
    WDAElementInfo,
    WDASession,
    WebDriverOptions,
    WebDriverRequestOptions,
)
from midscene.webdriver.clients.webdriver_client import (
    DEFAULT_WDA_PORT,
    WebDriverClient,
)

__all__ = [
    "DEFAULT_WDA_PORT",
    "DeviceInfo",
    "Point",
    "Size",
    "WDAElement",
    "WDAElementInfo",
    "WDASession",
    "WebDriverClient",
    "WebDriverOptions",
    "WebDriverRequestOptions",
]
