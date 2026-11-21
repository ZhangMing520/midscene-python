"""iOS WebDriverAgent backend.

Synced from upstream packages/ios/src/ios-webdriver-client.ts. Appium/WDA
specific endpoints layered on the shared W3C client from `midscene.webdriver`.
"""

import asyncio
import json
import time
from typing import Any, Dict, Optional

from loguru import logger

from midscene.webdriver import (
    WebDriverClient,
    WebDriverRequestError,
    element_id_from,
    is_missing_endpoint,
)

WDA_MJPEG_SCREENSHOT_QUALITY = 50
WDA_MJPEG_FRAMERATE = 30
WDA_MJPEG_SCALING_FACTOR = 100

TEXT_INPUT_TYPES = (
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeTextView",
    "XCUIElementTypeSearchField",
)


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

    async def _find_identified_inputs(self, name: str, element_type: str) -> list:
        """Elements whose name is a real identifier and whose type matches.

        WDA falls back to label when the accessibility identifier is empty;
        excluding that case proves the name identifies the field on both the
        old and the current snapshot.
        """
        response = await self._request(
            "POST",
            "/elements",
            {
                "using": "predicate string",
                "value": (
                    f"name == {json.dumps(name)} AND name != label "
                    f"AND type == {json.dumps(element_type)}"
                ),
            },
        )
        value = response.get("value")
        if not isinstance(value, list):
            raise RuntimeError("Invalid WDA input search response")
        ids = [element_id_from(item) for item in value]
        if any(element_id is None for element_id in ids):
            raise RuntimeError("Missing WDA input element ID")
        return ids

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

        # Re-identification is only a recovery hint: a failed lookup must not
        # stop the clear itself from being attempted.
        name = ""
        element_type: Any = None
        try:
            raw_name = await self.get_element_attribute(original_id, "name")
            name = raw_name if isinstance(raw_name, str) else ""
            element_type = await self.get_element_attribute(original_id, "type")
        except WebDriverRequestError:
            name = ""
            element_type = None
        is_text_input = (
            isinstance(element_type, str) and element_type in TEXT_INPUT_TYPES
        )
        can_reacquire = False
        if name and is_text_input:
            try:
                named = await self._find_identified_inputs(name, element_type)
            except WebDriverRequestError:
                named = []
            can_reacquire = len(named) == 1 and named[0] == original_id
        target_id = original_id

        # One retry is allowed after a stale clear: the field may have been
        # re-created, in which case the retry targets the re-identified id. A
        # successful clear response proves the operation completed without
        # guessing whether the accessibility value is text or placeholder text.
        retries_left = 1
        while True:
            clear_error: Optional[BaseException] = None
            try:
                await self._request("POST", f"/element/{target_id}/clear")
            except WebDriverRequestError as e:
                if e.error_code != "stale element reference":
                    raise
                clear_error = e

            if await self.get_active_element_id() != target_id:
                try:
                    await self._request("POST", f"/element/{target_id}/click")
                except WebDriverRequestError as e:
                    if e.error_code != "stale element reference" or not can_reacquire:
                        raise
                    matches = await self._find_identified_inputs(name, element_type)
                    if len(matches) != 1:
                        raise RuntimeError(
                            "Cannot uniquely identify input after clearing the field"
                        )
                    target_id = matches[0]
                    await self._request("POST", f"/element/{target_id}/click")
                if await self.get_active_element_id() != target_id:
                    raise RuntimeError(
                        "Failed to restore input focus after clearing the field"
                    )

            if clear_error is None:
                return True
            value = await self.get_element_attribute(target_id, "value")
            if value is None or value == "":
                return True
            if retries_left == 0:
                raise RuntimeError(
                    "Cannot verify that input was cleared; refusing to append text"
                ) from clear_error
            retries_left -= 1

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
