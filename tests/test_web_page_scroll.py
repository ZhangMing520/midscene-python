"""Synced from upstream packages/web-integration/tests/unit-test/base-page-swipe.test.ts
and bridge/io.test.ts (mouse wheel forwarding)."""

from unittest.mock import AsyncMock, patch

import pytest


class TestWebPageScroll:
    @pytest.mark.asyncio
    async def test_playwright_scroll_defaults_to_viewport_and_centers_mouse(self):
        from midscene.web_integration.playwright.page import PlaywrightWebPage

        class Mouse:
            def __init__(self):
                self.calls = []

            async def move(self, x, y):
                self.calls.append(("move", x, y))

            async def wheel(self, x, y):
                self.calls.append(("wheel", x, y))

        class Page:
            def __init__(self):
                self.mouse = Mouse()
                self.viewport_size = {"width": 1000, "height": 800}

        page = PlaywrightWebPage.__new__(PlaywrightWebPage)
        page.page = Page()
        with patch(
            "midscene.web_integration.playwright.page.asyncio.sleep", AsyncMock()
        ):
            await page.scroll("down")
            await page.scroll("right")
        assert page.page.mouse.calls == [
            ("move", 500, 400),
            ("wheel", 0, 560.0),
            ("move", 500, 400),
            ("wheel", 700.0, 0),
        ]

    @pytest.mark.asyncio
    async def test_bridge_scroll_defaults_to_viewport_and_centers_mouse(self):
        from midscene.web_integration.bridge_mode import BridgeWebPage

        class Server:
            def __init__(self):
                self.calls = []

            async def call(self, name, args):
                self.calls.append((name, args))
                if name == "size":
                    return {"width": 1000, "height": 800}
                return None

        page = BridgeWebPage()
        page._server = Server()
        page._connected = True
        await page.scroll("up")
        assert page._server.calls == [
            ("size", []),
            ("mouse.move", [500, 400]),
            ("mouse.wheel", [0, -560.0]),
        ]
