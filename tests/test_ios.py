"""
Tests for the iOS device layer (upstream packages/ios).
All WDA HTTP calls go through a fake transport; no device required.
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

import pytest

from midscene.ios.wda import WebDriverAgentBackend, WebDriverRequestError


class FakeWDARequests:
    """Records (method, path, body) and returns canned responses.

    A canned value that is an Exception is raised instead of returned, which
    is how a WDA build reports protocol errors. A list answers one entry per
    call and repeats the last entry once they run out.
    """

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses = responses or {}
        self.requests: List[tuple] = []
        self.hits: Dict[str, int] = {}

    async def __call__(self, method, path, body=None):
        self.requests.append((method, path, body))
        # replace the session id in both sides so patterns don't need it
        key = re.sub(r"(/session/)[^/]+", r"\1X", f"{method} {path}")
        for pattern in self.responses:
            normalized_pattern = re.sub(r"(/session/)[^/]+", r"\1X", pattern)
            if key.startswith(normalized_pattern):
                result = self.responses[pattern]
                if isinstance(result, list):
                    index = self.hits.get(pattern, 0)
                    self.hits[pattern] = index + 1
                    result = result[min(index, len(result) - 1)]
                if isinstance(result, Exception):
                    raise result
                return result
        raise RuntimeError(f"WDA request failed (404) {method} {path}")

    def calls_for(self, fragment: str) -> List[tuple]:
        return [r for r in self.requests if fragment in r[1]]


def _backend(responses: Optional[Dict[str, Any]] = None, session_id: str = "wda-1"):
    backend = WebDriverAgentBackend(base_url="http://localhost:8100")
    canned = dict(responses or {})
    # unmatched endpoints answer with an empty body; keeping this entry last
    # means the specific patterns above still win
    canned.setdefault("", {})
    transport = FakeWDARequests(canned)
    backend.make_request = transport  # type: ignore
    backend.session_id = session_id
    backend.owns_session = False
    return backend, transport


def device_action_space(device):
    """The action space the planner would see for this device."""
    from midscene.core.actions import build_action_space_for

    return build_action_space_for(device.interface_type)


class TestWebDriverAgentBackend:
    @pytest.mark.asyncio
    async def test_tap_with_legacy_fallback(self):
        """Only a missing route may retry the WDA 5.x endpoint."""
        backend, transport = _backend({
            # listed first: the fake matches by prefix, so /wda/tap would
            # otherwise swallow the legacy route too
            "POST /session/X/wda/tap/0": {},
            "POST /session/X/wda/tap": WebDriverRequestError(
                "WebDriver request failed (404) POST /session/wda-1/wda/tap",
                404,
                "unknown method",
            ),
        })
        await backend.tap(10, 20)
        assert any("/wda/tap/0" in r[1] for r in transport.requests)

    @pytest.mark.asyncio
    async def test_tap_does_not_replay_after_server_error(self):
        """A 5xx means the gesture may already have landed; a second tap would
        be an unintended interaction."""
        backend, transport = _backend({
            "POST /session/X/wda/tap": WebDriverRequestError(
                "WebDriver request failed (500) POST /session/wda-1/wda/tap", 500
            ),
        })
        with pytest.raises(WebDriverRequestError):
            await backend.tap(10, 20)
        assert not transport.calls_for("/wda/tap/0")

    @pytest.mark.asyncio
    async def test_screenshot_rejects_unusable_payload(self):
        backend, _ = _backend({"GET /session/X/screenshot": {"value": {"error": "x"}}})
        with pytest.raises(RuntimeError, match="screenshot payload"):
            await backend.take_screenshot()

    @pytest.mark.asyncio
    async def test_clear_active_element_verifies_the_field_is_empty(self):
        backend, transport = _backend({
            "GET /session/X/element/active": {
                "value": {"element-6066-11e4-a52e-4f735466cecf": "e1"}
            },
            "GET /session/X/element/e1/attribute/value": {"value": ""},
        })
        assert await backend.clear_active_element() is True
        assert transport.calls_for("/element/e1/clear")

    @pytest.mark.asyncio
    async def test_clear_active_element_refuses_unverified_clear(self):
        """The field still reads its old text: typing would append to it."""
        backend, _ = _backend({
            "GET /session/X/element/active": {"value": {"ELEMENT": "e1"}},
            "GET /session/X/element/e1/attribute/value": {"value": "old text"},
        })
        with pytest.raises(RuntimeError, match="refusing to append text"):
            await backend.clear_active_element()

    @pytest.mark.asyncio
    async def test_clear_active_element_without_focus(self):
        backend, transport = _backend({
            "GET /session/X/element/active": {"value": None},
        })
        assert await backend.clear_active_element() is False
        assert not transport.calls_for("/clear")

    @pytest.mark.asyncio
    async def test_clear_active_element_on_wda_without_active_api(self):
        """Older WDA builds answer the active-element lookup with 'unknown
        command'; the caller then falls back to plain typing."""
        backend, _ = _backend({
            "GET /session/X/element/active": WebDriverRequestError(
                "WebDriver request failed (404) GET /session/wda-1/element/active",
                404,
                "unknown command",
            ),
        })
        assert await backend.clear_active_element() is False

    @pytest.mark.asyncio
    async def test_swipe_uses_w3c_actions(self):
        backend, transport = _backend()
        await backend.swipe(10, 100, 10, 500, duration=300)
        call = transport.calls_for("/actions")[0]
        body = call[2]
        pointer = body["actions"][0]
        assert pointer["parameters"]["pointerType"] == "touch"
        moves = [a for a in pointer["actions"] if a["type"] == "pointerMove"]
        assert moves[0]["x"] == 10 and moves[0]["y"] == 100
        assert moves[-1]["y"] == 500
        assert moves[-1]["duration"] == 300

    @pytest.mark.asyncio
    async def test_pinch_two_fingers(self):
        backend, transport = _backend()
        await backend.pinch(200, 400, 300, 20, duration=500)
        call = transport.calls_for("/actions")[0]
        fingers = call[2]["actions"]
        assert len(fingers) == 2
        f1_moves = [a for a in fingers[0]["actions"] if a["type"] == "pointerMove"]
        # finger1 starts below center (y + 150) and ends near center (y + 10)
        assert f1_moves[0]["y"] == 550 and f1_moves[-1]["y"] == 410

    @pytest.mark.asyncio
    async def test_type_text_char_array(self):
        backend, transport = _backend()
        await backend.type_text("hi")
        call = transport.calls_for("/wda/keys")[0]
        assert call[2] == {"value": ["h", "i"]}

    @pytest.mark.asyncio
    async def test_press_key_newline_for_enter(self):
        backend, transport = _backend()
        await backend.press_key("Enter")
        call = transport.calls_for("/wda/keys")[0]
        assert call[2] == {"value": ["\n"]}

    @pytest.mark.asyncio
    async def test_press_key_rejects_combinations(self):
        backend, _ = _backend()
        with pytest.raises(RuntimeError) as exc:
            await backend.press_key("Control+A")
        assert "combinations" in str(exc.value)

    @pytest.mark.asyncio
    async def test_launch_terminate_open_url(self):
        backend, transport = _backend()
        await backend.launch_app("com.example.app")
        await backend.terminate_app("com.example.app")
        await backend.open_url("https://example.com")
        assert transport.calls_for("/wda/apps/launch")
        assert transport.calls_for("/wda/apps/terminate")
        assert transport.calls_for("/url")

    @pytest.mark.asyncio
    async def test_press_home_button(self):
        backend, transport = _backend()
        await backend.press_home_button()
        assert transport.calls_for("/wda/pressButton")

    @pytest.mark.asyncio
    async def test_create_session_applies_ios_defaults(self):

        backend = WebDriverAgentBackend(base_url="http://localhost:8100")
        transport = FakeWDARequests({
            "POST /session/X": {"sessionId": "s1", "capabilities": {}},
        })
        backend.make_request = transport  # type: ignore

        settings_calls: List[tuple] = []

        async def settings_wrapper(method, path, body=None):
            if "/appium/settings" in path:
                settings_calls.append(body)
                return {}
            if path == "/session":
                return {"sessionId": "s1", "capabilities": {}}
            return await transport(method, path, body)

        backend.make_request = settings_wrapper  # type: ignore
        session = await backend.create_session()
        assert session["sessionId"] == "s1"
        assert settings_calls and settings_calls[0]["snapshotMaxDepth"] == 50


class TestIOSDevice:
    """Device-level tests: the gestures must satisfy the AbstractInterface
    contract the action-space executors call them through."""

    SCREEN = {"GET /session/X/window/rect": {"value": {"width": 390, "height": 844}}}

    def _device(self, responses: Optional[Dict[str, Any]] = None):
        from midscene.ios.device import IOSDevice

        device = IOSDevice()
        # the screen size is needed by every gesture; "" keeps unrelated
        # endpoints answering with an empty body
        canned = {**self.SCREEN, **(responses or {}), "": {}}
        backend, transport = _backend(canned)
        device.wda = backend
        device._connected = True
        return device, transport

    @pytest.mark.asyncio
    async def test_swipe_direction_contract(self):
        """swipe(direction, distance=...) is what _execute_swipe calls."""
        device, transport = self._device()
        await device.swipe("up", distance=300)
        moves = [
            a for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        # finger-movement convention: "up" starts below the centre (422+150)
        assert (moves[0]["x"], moves[0]["y"]) == (195, 572)
        assert (moves[-1]["x"], moves[-1]["y"]) == (195, 272)

    @pytest.mark.asyncio
    async def test_scroll_reveals_content_and_honours_point(self):
        """Scroll names the content to reveal, so the finger moves the other
        way (upstream scrollDown swipes upward)."""
        device, transport = self._device()
        await device.scroll("down", distance=round(844 / 3))
        moves = [
            a for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        assert moves[0]["y"] == 422
        assert moves[-1]["y"] == 422 - round(844 / 3)

        device, transport = self._device()
        await device.scroll("left", point=[100, 300])
        moves = [
            a for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        # scrollLeft brings the left content in: finger travels right
        assert moves[0]["x"] == 100
        assert moves[-1]["x"] == 100 + round(390 * 0.7)

    @pytest.mark.asyncio
    async def test_untargeted_scroll_uses_the_slow_default_gesture(self):
        """Upstream scrollDefault: cross the central 70% slowly enough that
        the release velocity cannot fling past the viewport."""
        device, transport = self._device()
        await device.scroll("down")
        moves = [
            a for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        assert (moves[0]["x"], moves[0]["y"]) == (195, round(844 * 0.85))
        assert moves[-1]["y"] == round(844 * 0.15)
        travel = round(844 * 0.85) - round(844 * 0.15)
        assert moves[-1]["duration"] == max(1000, round(travel / 0.4))

        device, transport = self._device()
        await device.scroll("right")
        moves = [
            a for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        # scrollRight reveals what is off to the right: the finger goes left
        assert moves[0]["x"] == round(390 * 0.85)
        assert moves[-1]["x"] == round(390 * 0.15)
        assert moves[0]["y"] == moves[-1]["y"] == round(844 / 2)

    @pytest.mark.asyncio
    async def test_pinch_contract_and_geometry(self):
        """Upstream normalizePinchParam: "out" spreads the fingers apart
        (zoom in), "in" pinches them together (zoom out)."""
        base = round(min(390, 844) / 4)

        device, transport = self._device()
        await device.pinch("out", point=[100, 200], distance=150, duration=800)
        fingers = transport.calls_for("/actions")[0][2]["actions"]
        moves = [a for a in fingers[0]["actions"] if a["type"] == "pointerMove"]
        assert moves[0]["y"] == round(200 + base / 2)
        assert moves[-1]["y"] == round(200 + (base + 150) / 2)
        assert moves[-1]["duration"] == 800

        device, transport = self._device()
        await device.pinch("in", point=[100, 200], distance=150)
        moves = [
            a
            for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        assert moves[0]["y"] == round(200 + base / 2)
        # a finger travel larger than the base still leaves a usable gap
        assert moves[-1]["y"] == round(200 + max(10, base - 150) / 2)

    @pytest.mark.asyncio
    async def test_gestures_run_through_the_action_space(self):
        """The executors resolve actions and call the primitives; a signature
        drift here used to raise TypeError."""
        from midscene.core.actions import find_action_in_action_space_or_throw

        async def fake_locate(*args, **kwargs):
            return {"center": [120, 300]}

        for name, param in [
            ("Swipe", {"direction": "up", "distance": 200}),
            ("Pinch", {"direction": "out"}),
            ("Scroll", {"direction": "down", "locate": {"prompt": "the list"}}),
        ]:
            device, transport = self._device()
            definition = find_action_in_action_space_or_throw(
                name, device_action_space(device)
            )
            await definition.execute(param, device, fake_locate)
            assert transport.calls_for("/actions")

    @pytest.mark.asyncio
    async def test_device_pixel_ratio_accessor_is_not_shadowed(self):
        """The scale cache used to share its name with the coroutine, which
        made the accessor 'NoneType' object is not callable."""
        device, transport = self._device({
            "GET /session/X/wda/screen": {"value": {"scale": 3.0}},
        })
        assert await device._device_pixel_ratio() == 3.0
        assert await device._device_pixel_ratio() == 3.0
        assert len(transport.calls_for("/wda/screen")) == 1

    @pytest.mark.asyncio
    async def test_run_wda_request_delegates(self):
        device, transport = self._device()
        await device.run_wda_request("POST", "/wda/lock", {})
        assert transport.calls_for("/wda/lock")

    @pytest.mark.asyncio
    async def test_run_wda_request_action_validates_params(self):
        from midscene.core.actions import find_action_in_action_space_or_throw

        device, transport = self._device()
        definition = find_action_in_action_space_or_throw(
            "RunWdaRequest", device_action_space(device)
        )
        with pytest.raises(ValueError):
            await definition.execute({"method": "PATCH", "endpoint": "/x"}, device, None)
        with pytest.raises(ValueError):
            await definition.execute({"method": "get", "endpoint": " "}, device, None)
        # a lowercase method is normalised before it reaches WDA
        await definition.execute(
            {"method": "post", "endpoint": "/wda/unlock", "data": {}}, device, None
        )
        assert transport.calls_for("/wda/unlock")[-1][0] == "POST"

    def test_ios_action_space_exposes_what_wda_implements(self):
        from midscene.core.actions import build_action_space_for

        names = {a.name for a in build_action_space_for("ios")}
        # upstream iOS advertises these, and the device implements them
        assert {
            "Tap",
            "DoubleClick",
            "LongPress",
            "Swipe",
            "Pinch",
            "Scroll",
            "Input",
            "ClearInput",
            "KeyboardPress",
            "Launch",
            "Terminate",
            "IOSHomeButton",
            "IOSAppSwitcher",
            "RunWdaRequest",
        } <= names
        # no mouse-only web actions on iOS
        assert not names & {"RightClick", "MiddleClick", "Hover", "DragAndDrop"}

    def test_ios_agent_filters_by_supported_primitives(self):
        from midscene.ios import IOSAgent

        device, _ = self._device()
        names = [a.name for a in IOSAgent(device).action_space]
        assert "Swipe" in names and "IOSHomeButton" in names
        assert "RightClick" not in names

    @pytest.mark.asyncio
    async def test_get_context(self):
        device, _ = self._device({
            "GET /session/X/screenshot": {"value": "pngbase64"},
            "GET /session/X/wda/screen": {"value": {"scale": 3.0}},
        })
        context = await device.get_context()
        assert context.size.width == 390
        assert context.size.height == 844
        assert context.screenshot_base64 == "data:image/png;base64,pngbase64"

    @pytest.mark.asyncio
    async def test_tap_delegates(self):
        device, transport = self._device()
        await device.tap(5, 6)
        assert transport.calls_for("/wda/tap")

    @pytest.mark.asyncio
    async def test_input_text_uses_wda_keys(self):
        device, transport = self._device()
        await device.input_text("abc")
        assert transport.calls_for("/wda/keys")

    # -- clearing ------------------------------------------------------------

    FOCUSED = {
        "GET /session/X/element/active": {"value": {"ELEMENT": "e1"}},
        "GET /session/X/element/e1/attribute/value": {"value": ""},
    }

    @pytest.mark.asyncio
    async def test_clear_input_uses_the_element_api(self):
        device, transport = self._device(dict(self.FOCUSED))
        await device.clear_input()
        assert transport.calls_for("/element/e1/clear")

    @pytest.mark.asyncio
    async def test_clear_input_fails_loudly_without_focus(self, monkeypatch):
        """Nothing is focused, so there is nothing to clear; silent typing
        would append to whatever the planner meant to replace."""
        from midscene.ios import device as device_module

        monkeypatch.setattr(device_module, "INPUT_FOCUS_TIMEOUT_MS", 0)
        device, transport = self._device(
            {"GET /session/X/element/active": {"value": None}}
        )
        with pytest.raises(RuntimeError, match="waiting for iOS input focus"):
            await device.clear_input()
        assert not transport.calls_for("/clear")

    @pytest.mark.asyncio
    async def test_replace_input_clears_before_typing(self):
        device, transport = self._device(dict(self.FOCUSED))
        await device.replace_input("new text")
        paths = [r[1] for r in transport.requests]
        clear_at = next(i for i, p in enumerate(paths) if p.endswith("/clear"))
        keys_at = next(i for i, p in enumerate(paths) if p.endswith("/wda/keys"))
        assert clear_at < keys_at

    @pytest.mark.asyncio
    async def test_input_action_replaces_when_the_device_can_clear(self):
        from midscene.core.actions import find_action_in_action_space_or_throw

        device, transport = self._device(dict(self.FOCUSED))
        definition = find_action_in_action_space_or_throw(
            "Input", device_action_space(device)
        )
        await definition.execute({"value": "hello"}, device, None)
        assert transport.calls_for("/element/e1/clear")
        assert transport.calls_for("/wda/keys")

    # -- scroll to boundary ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_scroll_to_bottom_flings_until_the_screen_stops(self, monkeypatch):
        from midscene.ios import device as device_module

        monkeypatch.setattr(device_module, "SCROLL_SETTLE_MS", 0)
        monkeypatch.setattr(device_module, "SCROLL_INERTIA_MS", 0)
        shots = [
            {"value": "A" * 400},
            {"value": "B" * 400},
            {"value": "B" * 400},
        ]
        device, transport = self._device({
            "GET /session/X/screenshot": [dict(s) for s in shots],
        })
        await device.scroll("down", scroll_type="scrollToBottom")

        gestures = transport.calls_for("/actions")
        assert len(gestures) == 2
        moves = [
            a for a in gestures[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        # the finger starts near the bottom edge and travels up by 0.6 * height
        assert moves[0]["y"] == round(844 * 0.8)
        assert moves[-1]["y"] == round(844 * 0.8) - round(844 * 0.6)
        assert moves[-1]["duration"] == 300

    @pytest.mark.asyncio
    async def test_scroll_to_top_anchors_near_the_top_edge(self, monkeypatch):
        from midscene.ios import device as device_module

        monkeypatch.setattr(device_module, "SCROLL_SETTLE_MS", 0)
        monkeypatch.setattr(device_module, "SCROLL_INERTIA_MS", 0)
        device, transport = self._device({
            "GET /session/X/screenshot": [
                {"value": "moving"}, {"value": "still"}, {"value": "still"},
            ],
        })
        await device.scroll("up", scroll_type="scrollToTop")
        moves = [
            a
            for a in transport.calls_for("/actions")[0][2]["actions"][0]["actions"]
            if a["type"] == "pointerMove"
        ]
        assert moves[0]["y"] == round(844 * 0.2)
        assert moves[-1]["y"] == round(844 * 0.2) + round(844 * 0.6)

    @pytest.mark.asyncio
    async def test_boundary_scroll_stops_at_the_attempt_cap(self, monkeypatch):
        """Endless animation must not turn into an unbounded gesture loop."""
        from midscene.ios import device as device_module

        monkeypatch.setattr(device_module, "SCROLL_SETTLE_MS", 0)
        monkeypatch.setattr(device_module, "SCROLL_INERTIA_MS", 0)
        monkeypatch.setattr(device_module, "SCROLL_MAX_ATTEMPTS", 4)
        device, transport = self._device({
            "GET /session/X/screenshot": [
                # long frames: the base64 text has to differ by more than the
                # tolerance, exactly as two real frames would
                {"value": chr(65 + i) * 300} for i in range(10)
            ],
        })
        await device.scroll("down", scroll_type="scrollToBottom")
        assert len(transport.calls_for("/actions")) == 4

    @pytest.mark.asyncio
    async def test_single_action_scroll_takes_no_screenshots(self):
        device, transport = self._device()
        await device.scroll("down", scroll_type="singleAction")
        assert len(transport.calls_for("/actions")) == 1
        assert not transport.calls_for("/screenshot")

    def test_screenshots_similar_tolerates_minor_change(self):
        from midscene.ios.device import _screenshots_similar

        assert _screenshots_similar("abcd", "abcd", 10)
        assert _screenshots_similar("a" * 1000, "b" * 20 + "a" * 980, 10)
        assert not _screenshots_similar("a" * 1000, "b" * 300 + "a" * 700, 10)
        assert not _screenshots_similar("a" * 100, "a" * 900, 10)
        assert not _screenshots_similar("", "abc", 10)

    # -- lifecycle ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_destroy_releases_the_session(self):
        device, _ = self._device()
        await device.destroy()
        assert device.wda.session_id is None
        assert device._connected is False
        await device.destroy()  # idempotent

    @pytest.mark.asyncio
    async def test_agent_destroys_the_interface(self):
        from midscene.ios import IOSAgent

        device, _ = self._device()
        agent = IOSAgent(device)
        await agent.destroy()
        assert device.wda.session_id is None

    # -- raw WDA passthrough ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_run_wda_request_returns_the_wda_payload(self):
        from midscene.core.actions import find_action_in_action_space_or_throw

        payload = {"value": {"bundleId": "com.example.app"}}
        device, _ = self._device({
            "GET /session/X/wda/activeAppInfo": payload,
        })
        definition = find_action_in_action_space_or_throw(
            "RunWdaRequest", device_action_space(device)
        )
        result = await definition.execute(
            {"method": "GET", "endpoint": "/wda/activeAppInfo"}, device, None
        )
        assert result == payload

    @pytest.mark.asyncio
    async def test_agent_surfaces_the_action_result(self):
        from midscene.ios import IOSAgent

        payload = {"value": {"bundleId": "com.example.app"}}
        device, _ = self._device({
            "GET /session/X/wda/activeAppInfo": payload,
        })
        agent = IOSAgent(device)
        result = await agent._call_action_in_action_space(
            "RunWdaRequest", {"method": "GET", "endpoint": "/wda/activeAppInfo"}
        )
        assert result == payload

    @pytest.mark.asyncio
    async def test_launch_app_url_vs_bundle(self):
        device, transport = self._device()
        await device.launch_app("https://example.com")
        await device.launch_app("com.example.app")
        assert transport.calls_for("/url")
        assert transport.calls_for("/wda/apps/launch")

    def test_interface_type(self):
        from midscene.core.types import InterfaceType

        device, _ = self._device()
        assert device.interface_type == InterfaceType.IOS

    def test_ios_agent(self):
        from midscene.ios import IOSAgent
        from midscene.ios.device import IOSDevice

        agent = IOSAgent(IOSDevice())
        assert agent.interface_type.value == "ios"


class TestWebDriverTransport:
    """The HTTP layer, exercised through an in-process transport (no device,
    no socket)."""

    @pytest.mark.asyncio
    async def test_http_client_is_reused(self):
        from midscene.ios.wda import WebDriverClient

        client = WebDriverClient(base_url="http://localhost:8100")
        try:
            first = await client._http()
            assert await client._http() is first
        finally:
            await client.close()
        assert first.is_closed

    @pytest.mark.asyncio
    async def test_http_client_is_rebuilt_after_close(self):
        from midscene.ios.wda import WebDriverClient

        client = WebDriverClient(base_url="http://localhost:8100")
        first = await client._http()
        await client.close()
        second = await client._http()
        try:
            assert second is not first
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_request_failure_carries_status_and_protocol_code(self):
        import httpx

        from midscene.ios.wda import (
            WebDriverClient,
            WebDriverRequestError,
            is_missing_endpoint,
        )

        def handler(request):
            return httpx.Response(
                404, json={"value": {"error": "unknown method", "message": "no route"}}
            )

        client = WebDriverClient(base_url="http://localhost:8100")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client._client_loop = asyncio.get_running_loop()
        with pytest.raises(WebDriverRequestError) as excinfo:
            await client.make_request("POST", "/wda/tap", {"x": 1})
        error = excinfo.value
        assert error.status_code == 404
        assert error.error_code == "unknown method"
        assert is_missing_endpoint(error)
        assert isinstance(error, RuntimeError)
        await client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
