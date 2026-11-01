"""WebDriverAgent (WDA) HTTP client — the iOS WebDriver layer.

Synced from upstream packages/webdriver/src/clients/WebDriverClient.ts
(v1.17.4). WDA is the W3C-WebDriver-compatible server that runs on iOS
devices; this client drives sessions, screenshots and window size over
its HTTP endpoints.
"""

import asyncio
import re
import time
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


W3C_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

TEXT_INPUT_TYPES = (
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeTextView",
    "XCUIElementTypeSearchField",
)


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
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def session_info(self) -> Optional[Dict[str, Any]]:
        if not self.session_id:
            return None
        return {"sessionId": self.session_id, "capabilities": {}}

    # -- transport ----------------------------------------------------------

    async def _http(self) -> httpx.AsyncClient:
        """One client per running loop, reused so keep-alive connections work.

        A client bound to a loop that is no longer ours cannot be closed from
        here, so it is simply dropped and its connections are collected.
        """
        loop = asyncio.get_running_loop()
        if self._client is not None and (
            self._client.is_closed or self._client_loop is not loop
        ):
            stale, self._client = self._client, None
            if self._client_loop is loop and not stale.is_closed:
                await stale.aclose()
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._client_loop = loop
        return self._client

    async def close(self) -> None:
        """Release the pooled connections (called from device destroy())."""
        client, self._client = self._client, None
        self._client_loop = None
        if client is not None and not client.is_closed:
            await client.aclose()

    async def make_request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        client = await self._http()
        response = await client.request(method, url, json=body)
        if response.status_code >= 400:
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            raise WebDriverRequestError(
                f"WebDriver request failed ({response.status_code}) "
                f"{method} {path}: {response.text[:500]}",
                response.status_code,
                protocol_error_code(error_body),
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
        payload = response.get("value") or response
        if not isinstance(payload, str) or not payload.strip():
            raise RuntimeError(
                f"Unexpected WebDriver screenshot payload: {str(payload)[:200]}"
            )
        return payload

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

    # -- input focus / clearing (upstream packages/ios/src/input-focus.ts) --------

    async def get_active_element_id(self) -> Optional[str]:
        """The id of the focused element, or None when nothing has focus."""
        try:
            response = await self._request("GET", "/element/active")
        except WebDriverRequestError as e:
            if e.error_code == "no such element":
                return None
            raise
        return element_id_from(response.get("value"))

    async def get_element_attribute(self, element_id: str, name: str) -> Any:
        response = await self._request(
            "GET", f"/element/{element_id}/attribute/{name}"
        )
        return response.get("value")

    async def wait_for_input_focus(self, timeout_ms: float = 3000.0) -> None:
        """Block until an element owns the keyboard, or fail loudly."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while not await self.get_active_element_id():
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Timed out waiting for iOS input focus after {int(timeout_ms)}ms"
                )
            await asyncio.sleep(0.05)

    async def clear_active_element(self) -> bool:
        """Clear the focused input and keep focus.

        Returns False when there is nothing to clear or this WDA build has no
        active-element API, so callers can fall back to plain typing. Raises
        when a clear cannot be verified: appending text to a field still full
        of the old value is worse than reporting failure.
        """
        try:
            original_id = await self.get_active_element_id()
        except WebDriverRequestError as e:
            if e.error_code in ("unknown command", "unsupported operation"):
                return False
            raise
        if not original_id:
            return False

        clear_error: Optional[BaseException] = None
        try:
            await self._request("POST", f"/element/{original_id}/clear")
        except WebDriverRequestError as e:
            # TODO(ios): upstream re-identifies a stale field by its
            # accessibility name (POST /elements + predicate string), clicks the
            # unique match and retries the clear once. Until that lookup exists
            # here a stale id only counts as cleared if the value reads back
            # empty.
            if e.error_code != "stale element reference":
                raise
            clear_error = e

        if await self.get_active_element_id() != original_id:
            await self._request("POST", f"/element/{original_id}/click")
            if await self.get_active_element_id() != original_id:
                raise RuntimeError(
                    "Failed to restore input focus after clearing the field"
                )

        value = await self.get_element_attribute(original_id, "value")
        if value is None or value == "":
            return True
        # TODO(ios): upstream also accepts value == placeholderValue when the
        # field can be re-identified uniquely; that needs POST /elements.
        raise RuntimeError(
            "Cannot verify that input was cleared; refusing to append text"
        ) from clear_error

    # -- pointer ------------------------------------------------------------------

    async def tap(self, x: float, y: float) -> None:
        """WDA 6.0+ /wda/tap; WDA 5.x only knows /wda/tap/0.

        Only a missing route may fall back: replaying the gesture after a
        timeout or a server-side failure would tap a second time.
        """
        try:
            await self._request("POST", "/wda/tap", {"x": x, "y": y})
        except WebDriverRequestError as e:
            if not is_missing_endpoint(e):
                raise
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
