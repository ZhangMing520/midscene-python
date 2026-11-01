"""
Tests for the iOS device layer (upstream packages/ios).
All WDA HTTP calls go through a fake transport; no device required.
"""

import re
from typing import Any, Dict, List, Optional

import pytest

from midscene.ios.wda import WebDriverAgentBackend


class FakeWDARequests:
    """Records (method, path, body) and returns canned responses."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses = responses or {}
        self.requests: List[tuple] = []

    async def __call__(self, method, path, body=None):
        self.requests.append((method, path, body))
        # replace the session id in both sides so patterns don't need it
        key = re.sub(r"(/session/)[^/]+", r"\1X", f"{method} {path}")
        for pattern in self.responses:
            normalized_pattern = re.sub(r"(/session/)[^/]+", r"\1X", pattern)
            if key.startswith(normalized_pattern):
                return self.responses[pattern]
        raise RuntimeError(f"WDA request failed (404) {method} {path}")

    def calls_for(self, fragment: str) -> List[tuple]:
        return [r for r in self.requests if fragment in r[1]]


def _backend(responses: Optional[Dict[str, Any]] = None, session_id: str = "wda-1"):
    backend = WebDriverAgentBackend(base_url="http://localhost:8100")
    transport = FakeWDARequests(responses if responses is not None else {"": {}})
    backend.make_request = transport  # type: ignore
    backend.session_id = session_id
    backend.owns_session = False
    return backend, transport


class TestWebDriverAgentBackend:
    @pytest.mark.asyncio
    async def test_tap_with_legacy_fallback(self):
        backend, transport = _backend()

        async def fail_new(method, path, body=None):
            if path == "/session/wda-1/wda/tap":
                raise RuntimeError("not found")
            return await transport(method, path, body)

        backend.make_request = fail_new
        await backend.tap(10, 20)
        assert any("/wda/tap/0" in r[1] for r in transport.requests)

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
    def _device(self, responses: Optional[Dict[str, Any]] = None):
        from midscene.ios.device import IOSDevice

        device = IOSDevice()
        backend, transport = _backend(responses)
        device.wda = backend
        device._connected = True
        return device, transport

    @pytest.mark.asyncio
    async def test_get_context(self):
        device, _ = self._device({
            "GET /session/X/screenshot": {"value": "pngbase64"},
            "GET /session/X/window/rect": {"value": {"width": 390, "height": 844}},
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
