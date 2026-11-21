"""WebDriver request error and protocol helpers.

Synced from upstream packages/webdriver/src/utils/request.ts plus the
protocol-error helpers used by the iOS WebDriver client.
"""

import re
from typing import Any, Optional

W3C_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


class WebDriverRequestError(RuntimeError):
    """A failed WebDriver request plus the protocol error code, if any.

    WDA reports errors as {"value": {"error": "<code>", ...}}; callers branch
    on that code (stale element, missing route) instead of matching message
    strings.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        error_code: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def protocol_error_code(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    value = body.get("value")
    if isinstance(value, dict) and isinstance(value.get("error"), str):
        return value["error"]
    if isinstance(body.get("error"), str):
        return body["error"]
    return None


def wda_error_code(error: BaseException) -> Optional[str]:
    """The WDA protocol error code carried by a failed request, if any."""
    if isinstance(error, WebDriverRequestError):
        return error.error_code
    match = re.search(r'"error"\s*:\s*"([^"]+)"', str(error))
    return match.group(1) if match else None


def is_missing_endpoint(error: BaseException) -> bool:
    """True when the server has no such route, so another endpoint may work."""
    if isinstance(error, WebDriverRequestError):
        if error.status_code in (404, 405):
            return True
        return bool(error.error_code) and error.error_code in (
            "unknown method",
            "unknown command",
        )
    return "unable to find a route" in str(error).lower()


def element_id_from(value: Any) -> Optional[str]:
    """W3C element id with the legacy ELEMENT fallback (upstream getElementId)."""
    if not isinstance(value, dict):
        return None
    for key in (W3C_ELEMENT_KEY, "ELEMENT"):
        element_id = value.get(key)
        if isinstance(element_id, str) and element_id:
            return element_id
    return None
