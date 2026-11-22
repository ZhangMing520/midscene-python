"""Synced from upstream packages/core/tests/unit-test/action-scroll.test.ts."""

import pytest


class TestActionScroll:
    @pytest.mark.asyncio
    async def test_scroll_executor_passes_distance_unchanged(self):
        from midscene.core.device import _execute_scroll
        from tests.core_helpers import MockInterface

        interface = MockInterface()
        await _execute_scroll({"direction": "down", "distance": 123}, interface, None)
        assert interface.scrolled[-1][1] == 123

    @pytest.mark.asyncio
    async def test_scroll_drops_unsupported_kwargs(self):
        from midscene.core.device import _execute_scroll

        class ScrollDevice:
            def __init__(self):
                self.calls = []

            async def scroll(self, direction, distance=None):
                self.calls.append((direction, distance))

        device = ScrollDevice()
        await _execute_scroll(
            {"direction": "down", "scrollType": "scrollToBottom", "distance": 120},
            device,
            None,
        )
        assert device.calls == [("down", 120)]

    @pytest.mark.asyncio
    async def test_scroll_passes_located_point(self):
        from midscene.core.device import _execute_scroll

        class ScrollDevice:
            def __init__(self):
                self.calls = []

            async def scroll(
                self, direction, distance=None, point=None, scroll_type=None
            ):
                self.calls.append((direction, distance, point, scroll_type))

        async def locate_fn(param):
            return {"center": [10, 20]}

        device = ScrollDevice()
        await _execute_scroll(
            {"direction": "down", "locate": {"prompt": "the product list"}},
            device,
            locate_fn,
        )
        assert device.calls == [("down", None, [10, 20], "singleAction")]

