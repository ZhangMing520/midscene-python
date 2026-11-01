"""WebDriverAgent (WDA) HTTP client — the iOS WebDriver layer.

Synced from upstream packages/webdriver/src/clients/WebDriverClient.ts
(v1.17.4). WDA is the W3C-WebDriver-compatible server that runs on iOS
devices; this client drives sessions, screenshots and window size over
its HTTP endpoints.
"""

import asyncio
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


WDA_MJPEG_SCREENSHOT_QUALITY = 50
WDA_MJPEG_FRAMERATE = 30
WDA_MJPEG_SCALING_FACTOR = 100


class WebDriverAgentBackend(WebDriverClient):
    """Appium/WDA-specific endpoints on top of the W3C client
    (upstream ios-webdriver-client.ts)."""

    async def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None):
        self._ensure_session()
        return await self.make_request(
            method, f"/session/{self.session_id}{path}", body
        )

    async def create_session(
        self, capabilities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """iOS defaults + appium settings (upstream createSession)."""
        defaults = {
            "platformName": "iOS",
            "automationName": "XCUITest",
            "shouldUseSingletonTestManager": False,
            "shouldUseTestManagerForVisibilityDetection": False,
        }
        merged = {**defaults, **(capabilities or {})}
        session = await super().create_session(merged)
        try:
            await self._request(
                "POST",
                "/appium/settings",
                {
                    "snapshotMaxDepth": 50,
                    "elementResponseAttributes": "type,label,name,value,rect,enabled,visible",
                    "mjpegServerScreenshotQuality": WDA_MJPEG_SCREENSHOT_QUALITY,
                    "mjpegServerFramerate": WDA_MJPEG_FRAMERATE,
                    "mjpegScalingFactor": WDA_MJPEG_SCALING_FACTOR,
                },
            )
        except Exception as e:
            logger.debug(f"failed to apply iOS session settings: {e}")
        return session

    async def setup_existing_session(self) -> None:
        self._ensure_session()
        # settings applied lazily through create_session-style call
        try:
            await self._request(
                "POST",
                "/appium/settings",
                {
                    "snapshotMaxDepth": 50,
                    "elementResponseAttributes": "type,label,name,value,rect,enabled,visible",
                },
            )
        except Exception as e:
            logger.debug(f"failed to apply iOS session settings: {e}")

    # -- apps ----------------------------------------------------------------

    async def launch_app(self, bundle_id: str) -> None:
        await self._request("POST", "/wda/apps/launch", {"bundleId": bundle_id})

    async def activate_app(self, bundle_id: str) -> None:
        await self._request("POST", "/wda/apps/activate", {"bundleId": bundle_id})

    async def terminate_app(self, bundle_id: str) -> None:
        await self._request("POST", "/wda/apps/terminate", {"bundleId": bundle_id})

    async def open_url(self, url: str) -> None:
        await self._request("POST", "/url", {"url": url})

    # -- buttons / keys ---------------------------------------------------------

    async def press_home_button(self) -> None:
        await self._request("POST", "/wda/pressButton", {"name": "home"})

    async def app_switcher(self) -> None:
        """Native drag from the home indicator (upstream appSwitcher)."""
        size = await self.get_window_size()
        center_x = round(size[0] / 2)
        start_y = max(0, size[1] - 1)
        end_y = round(size[1] * 0.5)
        await self._request(
            "POST",
            "/wda/dragfromtoforduration",
            {"fromX": center_x, "fromY": start_y, "toX": center_x, "toY": end_y, "duration": 1},
        )
        await asyncio.sleep(0.8)

    async def type_text(self, text: str) -> None:
        """WDA keys endpoint requires an array of characters."""
        await self._request("POST", "/wda/keys", {"value": list(text.strip())})

    async def press_key(self, key: str) -> None:
        """iOS key support is deliberately narrow (upstream pressKey)."""
        if key.strip() != "+" and "+" in key:
            raise RuntimeError(
                f"iOS keyboardPress does not support key combinations: {key!r}"
            )
        if key in ("Enter", "Return", "return"):
            await self._request("POST", "/wda/keys", {"value": ["\n"]})
            await asyncio.sleep(0.1)
            return
        if key in ("Backspace", "Delete"):
            await self._request("POST", "/wda/keys", {"value": ["\b"]})
            return
        if key == "Space":
            await self._request("POST", "/wda/keys", {"value": [" "]})
            return

        ios_key_map = {
            "Tab": "\t",
            "ArrowUp": "\uE013",
            "ArrowDown": "\uE015",
            "ArrowLeft": "\uE012",
            "ArrowRight": "\uE014",
            "Home": "\uE011",
            "End": "\uE010",
        }
        if key in ios_key_map:
            await self._request("POST", "/wda/keys", {"value": [ios_key_map[key]]})
            return
        if len(key) == 1:
            await self._request("POST", "/wda/keys", {"value": [key]})
            return
        raise RuntimeError(f'Key "{key}" is not supported on iOS platform')

    # -- pointer ------------------------------------------------------------------

    async def tap(self, x: float, y: float) -> None:
        """WDA 6.0+ /wda/tap with legacy /wda/tap/0 fallback."""
        try:
            await self._request("POST", "/wda/tap", {"x": x, "y": y})
        except Exception:
            await self._request("POST", "/wda/tap/0", {"x": x, "y": y})

    async def double_tap(self, x: float, y: float) -> None:
        await self._request(
            "POST", "/wda/doubleTap", {"x": x, "y": y}
        )

    async def long_press(self, x: float, y: float, duration: float = 1000.0) -> None:
        await self._request(
            "POST",
            "/wda/touchAndHold",
            {"x": x, "y": y, "duration": duration / 1000.0},
        )

    async def swipe(
        self, from_x: float, from_y: float, to_x: float, to_y: float,
        duration: float = 500.0,
    ) -> None:
        """W3C Actions API pointer sequence (upstream swipe)."""
        actions = {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": from_x, "y": from_y},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {"type": "pointerMove", "duration": duration, "x": to_x, "y": to_y},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        }
        await self._request("POST", "/actions", actions)

    async def pinch(
        self, center_x: float, center_y: float,
        start_distance: float, end_distance: float, duration: float = 500.0,
    ) -> None:
        """Two-finger W3C Actions pinch (upstream pinch)."""
        half_start = start_distance / 2
        half_end = end_distance / 2

        def finger(finger_id: str, sign: int) -> Dict[str, Any]:
            return {
                "type": "pointer",
                "id": finger_id,
                "parameters": {"pointerType": "touch"},
                "actions": [
                    {
                        "type": "pointerMove",
                        "duration": 0,
                        "x": center_x,
                        "y": round(center_y + sign * half_start),
                    },
                    {"type": "pointerDown", "button": 0},
                    {"type": "pause", "duration": 100},
                    {
                        "type": "pointerMove",
                        "duration": duration,
                        "x": center_x,
                        "y": round(center_y + sign * half_end),
                    },
                    {"type": "pointerUp", "button": 0},
                ],
            }

        await self._request(
            "POST",
            "/actions",
            {"actions": [finger("finger1", 1), finger("finger2", -1)]},
        )

    # -- screen -----------------------------------------------------------------

    async def get_screen_scale(self) -> Optional[float]:
        try:
            response = await self._request("GET", "/wda/screen")
            value = (response or {}).get("value") or {}
            if value.get("scale"):
                return float(value["scale"])
        except Exception as e:
            logger.debug(f"failed to get screen scale: {e}")
        return None

    async def execute_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ):
        """Direct WDA API access (iOS equivalent of runAdbShell)."""
        return await self._request(method, endpoint, data)
