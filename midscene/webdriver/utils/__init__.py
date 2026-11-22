"""WebDriver request and URL helpers (upstream packages/webdriver/src/utils)."""

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
    "W3C_ELEMENT_KEY",
    "WebDriverRequestError",
    "element_id_from",
    "is_missing_endpoint",
    "make_web_driver_request",
    "normalize_web_driver_base_url",
    "normalize_webdriver_base_url",
    "protocol_error_code",
    "wda_error_code",
]
