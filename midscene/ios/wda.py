"""WebDriverAgent (WDA) HTTP client — the iOS WebDriver layer.

Synced from upstream packages/webdriver/src/clients/WebDriverClient.ts
(v1.17.4). WDA is the W3C-WebDriver-compatible server that runs on iOS
devices; this client drives sessions, screenshots and window size over
its HTTP endpoints.
"""

from typing import Any, Dict, Optional, Tuple

import httpx
from loguru import logger

DEFAULT_WDA_PORT = 8100


def normalize_webdriver_base_url(base_url: str) -> str:
    """Strip trailing slashes and any /wd/hub suffix handling (upstream
    normalizeWebDriverBaseUrl keeps the path as-is minus trailing slash)."""
    url = base_url.rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    return url


class WebDriverClient:
    """W3C-WebDriver-flavoured HTTP client for WebDriverAgent."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = DEFAULT_WDA_PORT,
        base_url: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.port = port
        self.host = host
        self.timeout = timeout
        self.base_url = (
            normalize_webdriver_base_url(base_url)
            if base_url is not None
            else f"http://{host}:{port}"
        )
        self.session_id: Optional[str] = session_id
        self.owns_session = session_id is None

    @property
    def session_info(self) -> Optional[Dict[str, Any]]:
        if not self.session_id:
            return None
        return {"sessionId": self.session_id, "capabilities": {}}

    # -- transport ----------------------------------------------------------

    async def make_request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, json=body)
        if response.status_code >= 400:
            raise RuntimeError(
                f"WebDriver request failed ({response.status_code}) "
                f"{method} {path}: {response.text[:500]}"
            )
        try:
            return response.json()
        except ValueError as e:
            raise RuntimeError(
                f"invalid JSON from WebDriver {method} {path}: {e}"
            ) from e

    def _ensure_session(self) -> None:
        if not self.session_id:
            raise RuntimeError("no active WebDriver session")

    # -- session management --------------------------------------------------

    async def create_session(
        self, capabilities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        response = await self.make_request(
            "POST",
            "/session",
            {"capabilities": {"alwaysMatch": dict(capabilities or {})}},
        )
        self.session_id = response.get("sessionId") or (
            response.get("value") or {}
        ).get("sessionId")
        self.owns_session = True
        if not self.session_id:
            raise RuntimeError("Failed to get session ID from response")
        caps = response.get("capabilities") or (response.get("value") or {}).get(
            "capabilities"
        )
        return {"sessionId": self.session_id, "capabilities": caps or {}}

    async def delete_session(self) -> None:
        if not self.session_id:
            return
        if not self.owns_session:
            logger.debug(f"Detached external session: {self.session_id}")
            self.session_id = None
            return
        try:
            await self.make_request("DELETE", f"/session/{self.session_id}")
        except Exception as e:
            logger.debug(f"Failed to delete session: {e}")
        finally:
            self.session_id = None

    # -- standard operations ---------------------------------------------------

    async def take_screenshot(self) -> str:
        self._ensure_session()
        response = await self.make_request(
            "GET", f"/session/{self.session_id}/screenshot"
        )
        return response.get("value") or response

    async def get_window_size(self) -> Tuple[int, int]:
        self._ensure_session()
        try:
            response = await self.make_request(
                "GET", f"/session/{self.session_id}/window/rect"
            )
            rect = response.get("value") or response
            return int(rect["width"]), int(rect["height"])
        except (KeyError, RuntimeError):
            # fall back to the legacy size endpoint
            response = await self.make_request(
                "GET", f"/session/{self.session_id}/window/size"
            )
            size = response.get("value") or response
            return int(size["width"]), int(size["height"])

    async def get_device_info(self) -> Optional[Dict[str, str]]:
        try:
            status = await self.make_request("GET", "/status")
            device = (status or {}).get("device")
            if device:
                return {
                    "udid": device.get("udid") or device.get("identifier") or "",
                    "name": device.get("name") or "",
                    "model": device.get("model") or device.get("productName") or "",
                }
            return None
        except Exception as e:
            logger.debug(f"Failed to get device info: {e}")
            return None
