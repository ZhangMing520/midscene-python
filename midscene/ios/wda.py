"""iOS WebDriverAgent backend.

Synced from upstream packages/ios/src/ios-webdriver-client.ts. Appium/WDA
specific endpoints layered on the shared W3C client from `midscene.webdriver`.
"""

import asyncio
import json
import math
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.ios.keyboard_dismiss import (
    KeyboardAccessoryButton,
    is_keyboard_accessory_toolbar,
    is_named_dismiss_button_near_keyboard,
    keyboard_accessory_toolbar_gap,
    select_keyboard_accessory_dismiss_button,
)
from midscene.shared.constants import WEBDRIVER_ELEMENT_ID_KEY
from midscene.webdriver import (
    WebDriverClient,
    WebDriverRequestError,
    element_id_from,
    is_missing_endpoint,
)

WDA_MJPEG_SCREENSHOT_QUALITY = 50
WDA_MJPEG_FRAMERATE = 30
WDA_MJPEG_SCALING_FACTOR = 100

KEYBOARD_DISMISS_DEADLINE_MS = 5000
KEYBOARD_DISMISS_POLL_INTERVAL_MS = 100


def _now_ms() -> float:
    return time.monotonic() * 1000


def _response_value(response: Any) -> Any:
    if isinstance(response, dict) and "value" in response:
        return response["value"]
    return response


def _element_ids_from_response(response: Any) -> List[str]:
    elements = _response_value(response)
    if not isinstance(elements, list):
        raise RuntimeError(f"Unexpected WDA elements response: {json.dumps(response)}")
    element_ids = []
    for index, element in enumerate(elements):
        element_id = None
        if isinstance(element, dict):
            element_id = element.get(WEBDRIVER_ELEMENT_ID_KEY) or element.get("ELEMENT")
        if not isinstance(element_id, str):
            raise RuntimeError(
                f"WDA element at index {index} has no element ID: "
                f"{json.dumps(element)}"
            )
        element_ids.append(element_id)
    return element_ids


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
        from midscene.ios.input_focus import wait_for_input_focus

        await wait_for_input_focus(self._request, timeout_ms)

    async def clear_active_element(self) -> bool:
        """Clear the focused input and keep focus (upstream input-focus)."""
        from midscene.ios.input_focus import clear_input_with_focus

        return await clear_input_with_focus(self._request)

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

    # -- keyboard dismissal -----------------------------------------------------

    async def type_raw_keys(self, chars: List[str]) -> None:
        """Send raw key events without trimming whitespace (typeRawKeys)."""
        await self._request("POST", "/wda/keys", {"value": list(chars)})

    async def find_element_ids(
        self,
        using: str,
        value: str,
        *,
        root_element_id: Optional[str] = None,
        deadline: Optional[float] = None,
    ) -> List[str]:
        endpoint = (
            f"/element/{root_element_id}/elements"
            if root_element_id
            else "/elements"
        )
        response = await self._keyboard_dismiss_request(
            "POST", endpoint, {"using": using, "value": value}, deadline
        )
        return _element_ids_from_response(response)

    async def get_element_rect(
        self, element_id: str, deadline: Optional[float] = None
    ) -> Dict[str, float]:
        response = await self._keyboard_dismiss_request(
            "GET", f"/element/{element_id}/rect", None, deadline
        )
        rect = _response_value(response)
        if not isinstance(rect, dict) or not all(
            isinstance(rect.get(key), (int, float))
            for key in ("x", "y", "width", "height")
        ):
            raise RuntimeError(f"Unexpected WDA element rect response: {response}")
        return {key: float(rect[key]) for key in ("x", "y", "width", "height")}

    async def click_element(
        self, element_id: str, deadline: Optional[float] = None
    ) -> None:
        await self._keyboard_dismiss_request(
            "POST", f"/element/{element_id}/click", None, deadline
        )

    async def _keyboard_dismiss_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]],
        deadline: Optional[float],
    ) -> Dict[str, Any]:
        self._ensure_session()
        timeout = None
        if deadline is not None:
            remaining = deadline - _now_ms()
            if remaining <= 0:
                raise RuntimeError(
                    "iOS keyboard dismissal exceeded its "
                    f"{KEYBOARD_DISMISS_DEADLINE_MS}ms deadline"
                )
            timeout = max(1, math.ceil(remaining)) / 1000
        return await self.make_request(
            method,
            f"/session/{self.session_id}{endpoint}",
            data,
            timeout=timeout,
        )

    async def find_visible_keyboard_ids(
        self, deadline: Optional[float] = None
    ) -> List[str]:
        return await self.find_element_ids(
            "predicate string",
            'type == "XCUIElementTypeKeyboard" AND visible == true',
            deadline=deadline,
        )

    async def get_visible_keyboard_rect(
        self, deadline: Optional[float] = None
    ) -> Optional[Dict[str, float]]:
        keyboard_ids = await self.find_visible_keyboard_ids(deadline)
        if not keyboard_ids:
            return None
        rects = []
        for keyboard_id in keyboard_ids:
            rect = await self.get_element_rect(keyboard_id, deadline)
            if rect["width"] > 0 and rect["height"] > 0:
                rects.append(rect)
        if not rects:
            raise RuntimeError("WDA reported a visible keyboard without a valid rect")
        return max(rects, key=lambda rect: rect["width"] * rect["height"])

    async def _dismiss_keyboard_by_name(
        self,
        key_names: List[str],
        keyboard_rect: Dict[str, float],
        deadline: float,
    ) -> bool:
        predicate_names = ", ".join(
            '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
            for name in key_names
        )
        button_ids = await self.find_element_ids(
            "predicate string",
            "type IN {\"XCUIElementTypeButton\", \"XCUIElementTypeKey\"} "
            "AND enabled == true AND visible == true AND "
            f"(name IN {{{predicate_names}}} OR label IN {{{predicate_names}}})",
            deadline=deadline,
        )
        nearby = []
        for button_id in button_ids:
            rect = await self.get_element_rect(button_id, deadline)
            if is_named_dismiss_button_near_keyboard(rect, keyboard_rect):
                nearby.append(
                    (
                        abs(rect["y"] + rect["height"] / 2 - keyboard_rect["y"]),
                        button_id,
                    )
                )
        if not nearby:
            return False
        nearby.sort(key=lambda item: item[0])
        await self.click_element(nearby[0][1], deadline)
        logger.debug(f"Dismissed keyboard using configured button: {', '.join(key_names)}")
        return True

    async def _dismiss_keyboard_using_accessory_toolbar(
        self,
        keyboard_rect: Dict[str, float],
        deadline: float,
    ) -> bool:
        toolbar_ids = await self.find_element_ids(
            "class name", "XCUIElementTypeToolbar", deadline=deadline
        )
        toolbar_candidates = []
        for toolbar_id in toolbar_ids:
            rect = await self.get_element_rect(toolbar_id, deadline)
            if is_keyboard_accessory_toolbar(rect, keyboard_rect):
                toolbar_candidates.append(
                    (abs(keyboard_accessory_toolbar_gap(rect, keyboard_rect)), toolbar_id, rect)
                )
        toolbar_candidates.sort(key=lambda item: item[0])

        for _, toolbar_id, toolbar_rect in toolbar_candidates:
            button_ids = await self.find_element_ids(
                "predicate string",
                'type == "XCUIElementTypeButton" AND enabled == true AND visible == true',
                root_element_id=toolbar_id,
                deadline=deadline,
            )
            buttons: List[KeyboardAccessoryButton] = []
            for button_id in button_ids:
                buttons.append(
                    {
                        "id": button_id,
                        "rect": await self.get_element_rect(button_id, deadline),
                    }
                )
            dismiss_button = select_keyboard_accessory_dismiss_button(
                toolbar_rect, buttons
            )
            if not dismiss_button:
                logger.debug(
                    f"Rejected keyboard accessory toolbar {toolbar_id}: expected "
                    "left navigation controls and exactly one right-edge dismiss control"
                )
                continue
            await self.click_element(dismiss_button["id"], deadline)
            logger.debug("Dismissed keyboard using the accessory toolbar button")
            return True
        return False

    async def _wait_for_keyboard_to_hide(self, deadline: float) -> bool:
        while _now_ms() < deadline:
            if not await self.find_visible_keyboard_ids(deadline):
                return True
            remaining = deadline - _now_ms()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(KEYBOARD_DISMISS_POLL_INTERVAL_MS, remaining) / 1000)
        return False

    async def dismiss_keyboard(self, key_names: Optional[List[str]] = None) -> bool:
        """Hide the software keyboard and wait until WDA confirms it is gone."""
        self._ensure_session()
        started_at = _now_ms()
        deadline = started_at + KEYBOARD_DISMISS_DEADLINE_MS

        keyboard_rect = await self.get_visible_keyboard_rect(deadline)
        if keyboard_rect is None:
            return True

        if key_names:
            dismissal_started = await self._dismiss_keyboard_by_name(
                key_names, keyboard_rect, deadline
            )
        else:
            dismissal_started = await self._dismiss_keyboard_using_accessory_toolbar(
                keyboard_rect, deadline
            )
        if not dismissal_started:
            return False

        hidden = await self._wait_for_keyboard_to_hide(deadline)
        logger.debug(
            f"Keyboard dismissal {'completed' if hidden else 'did not complete'} "
            f"in {int(_now_ms() - started_at)}ms"
        )
        return hidden

    async def is_keyboard_visible(self) -> bool:
        self._ensure_session()
        return bool(await self.find_visible_keyboard_ids())

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
