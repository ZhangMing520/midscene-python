"""WebDriver request error and protocol helpers.

Synced from upstream packages/webdriver/src/utils/request.ts plus the
protocol-error helpers used by the iOS WebDriver client.
"""

import asyncio
import json
import re
from typing import Any

import httpx
from loguru import logger

W3C_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

DEFAULT_REQUEST_TIMEOUT_MS = 30000


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
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


async def make_webdriver_request(
    base_url: str,
    method: str,
    path: str,
    body: Any | None = None,
    timeout_ms: int | None = None,
) -> Any:
    """Perform one WebDriver HTTP request (upstream makeWebDriverRequest).

    The timeout is a single deadline covering the response body as well, so a
    server that stalls mid-body still fails instead of hanging.
    """
    timeout = DEFAULT_REQUEST_TIMEOUT_MS if timeout_ms is None else timeout_ms
    url = f"{base_url}{path}"
    logger.debug(
        f"{method} {path}"
        + (f" with data: {json.dumps(body)}" if body is not None else "")
    )

    async def _perform() -> Any:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.request(
                method,
                url,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=json.dumps(body) if body is not None else None,
            )
            content_type = response.headers.get("content-type") or ""
            if "application/json" in content_type:
                response_data = response.json()
            else:
                response_data = response.text
            return response, response_data

    try:
        response, response_data = await asyncio.wait_for(
            _perform(), timeout=timeout / 1000
        )
    except (TimeoutError, httpx.TimeoutException) as error:
        raise WebDriverRequestError(f"Request timeout after {timeout}ms", 0) from error
    except Exception as error:
        logger.debug(f"Request failed: {error}")
        raise WebDriverRequestError(f"Request failed: {error}", 0) from error

    if response.status_code >= 400:
        error_message = None
        if isinstance(response_data, dict):
            error_message = response_data.get("error") or response_data.get("message")
        error_message = error_message or f"HTTP {response.status_code}"
        raise WebDriverRequestError(
            f"WebDriver request failed: {error_message}",
            response.status_code,
            protocol_error_code(response_data),
        )

    return response_data


async def make_web_driver_request(
    base_url: str,
    method: str,
    path: str,
    body: Any | None = None,
    timeout_ms: int | None = None,
) -> Any:
    """Upstream-named alias for :func:`make_webdriver_request`."""
    return await make_webdriver_request(base_url, method, path, body, timeout_ms)


def protocol_error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    value = body.get("value")
    if isinstance(value, dict) and isinstance(value.get("error"), str):
        return value["error"]
    if isinstance(body.get("error"), str):
        return body["error"]
    return None


def wda_error_code(error: BaseException) -> str | None:
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


def element_id_from(value: Any) -> str | None:
    """W3C element id with the legacy ELEMENT fallback (upstream getElementId)."""
    if not isinstance(value, dict):
        return None
    for key in (W3C_ELEMENT_KEY, "ELEMENT"):
        element_id = value.get(key)
        if isinstance(element_id, str) and element_id:
            return element_id
    return None
