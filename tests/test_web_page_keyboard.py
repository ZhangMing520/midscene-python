"""Synced from upstream packages/web-integration/tests/unit-test/
web-actions-navigation.test.ts and action-keyboard-press.test.ts."""

from typing import List

import pytest


class TestWebPageKeyboard:
    class RecordingServer:
        def __init__(self):
            self.calls: List[tuple] = []

        async def call(self, method, args=None, timeout=None):
            self.calls.append((method, args))
            if method == "size":
                return {"width": 100, "height": 50}
            if method == "screenshotBase64":
                return "data:image/jpeg;base64,AAAA"
            return None

    def _connected_page(self):
        from midscene.web_integration.bridge_mode import BridgeWebPage

        page = BridgeWebPage()
        recorder = self.RecordingServer()
        page._server = recorder
        page._connected = True
        return page, recorder

    def test_build_key_commands_matches_extension_shape(self):
        from midscene.web_integration.web_page import build_key_commands

        assert build_key_commands("Enter") == [{"key": "Enter"}]
        assert build_key_commands("Control+A") == [
            {"key": "Control"},
            {"key": "A", "command": "SelectAll"},
        ]
        assert build_key_commands("Command+C") == [
            {"key": "Meta"},
            {"key": "C", "command": "Copy"},
        ]
        assert build_key_commands("page down") == [{"key": "PageDown"}]
        assert build_key_commands("+") == [{"key": "+"}]


    @pytest.mark.asyncio
    async def test_keyboard_press_sends_key_objects(self):
        # the extension dispatches CDP Input.dispatchKeyEvent from {key, command}
        page, recorder = self._connected_page()
        await page.keyboard_press("Enter")
        assert recorder.calls[-1] == ("keyboard.press", [[{"key": "Enter"}]])
        await page.keyboard_press("Control+A")
        assert recorder.calls[-1] == (
            "keyboard.press",
            [[{"key": "Control"}, {"key": "A", "command": "SelectAll"}]],
        )

