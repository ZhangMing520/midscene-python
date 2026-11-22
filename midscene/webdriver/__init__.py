"""WebDriver client package (upstream @midscene/webdriver).

The WDA-specific iOS backend lives in `midscene.ios.wda`
(upstream packages/ios/src/ios-webdriver-client.ts).
"""

from midscene.webdriver.clients.webdriver_client import (
    DEFAULT_WDA_PORT,
    WebDriverClient,
)
from midscene.webdriver.managers import BaseServiceManager, WDAManager
from midscene.webdriver.utils.base_url import (
    normalize_web_driver_base_url,
    normalize_webdriver_base_url,
)
from midscene.webdriver.utils.request import (
    W3C_ELEMENT_KEY,
    WebDriverRequestError,
    element_id_from,
    is_missing_endpoint,
    make_web_driver_request,
    protocol_error_code,
    wda_error_code,
)

__all__ = [
    "DEFAULT_WDA_PORT",
    "W3C_ELEMENT_KEY",
    "BaseServiceManager",
    "WebDriverClient",
    "WebDriverRequestError",
    "WDAManager",
    "element_id_from",
    "is_missing_endpoint",
    "make_web_driver_request",
    "normalize_web_driver_base_url",
    "normalize_webdriver_base_url",
    "protocol_error_code",
    "wda_error_code",
]
