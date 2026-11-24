"""Typed shapes for the WebDriver clients.

Synced from upstream packages/webdriver/src/clients/types.ts.
"""

from typing import Any, TypedDict

from midscene.shared.constants import WEBDRIVER_ELEMENT_ID_KEY


class WDASession(TypedDict):
    sessionId: str
    capabilities: dict[str, Any]


WDAElement = TypedDict(
    "WDAElement",
    {
        "ELEMENT": str,
        WEBDRIVER_ELEMENT_ID_KEY: str,
    },
)


class WDAElementRect(TypedDict):
    x: float
    y: float
    width: float
    height: float


class WDAElementInfo(TypedDict):
    type: str
    name: str
    label: str
    value: str
    rect: WDAElementRect
    enabled: bool
    visible: bool


class WebDriverOptions(TypedDict, total=False):
    """Connection options for creating or attaching to a WebDriver session."""

    baseUrl: str
    port: int
    host: str
    timeout: float
    sessionId: str | None


class WebDriverRequestOptions(TypedDict, total=False):
    """Per-request overrides for WebDriver transport calls."""

    timeout: float


class Point(TypedDict):
    x: float
    y: float


class Size(TypedDict):
    width: int
    height: int


class DeviceInfo(TypedDict):
    udid: str
    name: str
    model: str


__all__ = [
    "DeviceInfo",
    "Point",
    "Size",
    "WDAElement",
    "WDAElementInfo",
    "WDAElementRect",
    "WDASession",
    "WebDriverOptions",
    "WebDriverRequestOptions",
]
