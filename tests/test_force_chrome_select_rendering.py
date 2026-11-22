"""Port of upstream packages/web-integration/tests/unit-test/force-chrome-select-rendering.test.ts."""

import pytest

from midscene.web_integration.common.browser_agent_utils import (
    apply_force_chrome_select_rendering,
)


class _MockPage:
    def __init__(self):
        self.evaluate_calls = 0
        self.init_scripts = []
        self.listeners = []

    async def evaluate(self, script, arg=None):
        self.evaluate_calls += 1
        return None

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event, handler):
        self.listeners.append((event, handler))


def _create_mock_page():
    return _MockPage()


@pytest.mark.asyncio
async def test_injects_the_style_and_registers_a_single_load_listener_per_page():
    """injects the style and registers a single load listener per page."""
    page = _create_mock_page()

    await apply_force_chrome_select_rendering(page)

    assert page.evaluate_calls == 1
    assert len(page.listeners) == 1
    event, handler = page.listeners[0]
    assert event == "load"
    assert callable(handler)


@pytest.mark.asyncio
async def test_is_a_no_op_when_called_again_for_the_same_page():
    """is a no-op when called again for the same page."""
    page = _create_mock_page()

    await apply_force_chrome_select_rendering(page)
    await apply_force_chrome_select_rendering(page)
    await apply_force_chrome_select_rendering(page)

    # still only injected once and only one load listener attached
    assert page.evaluate_calls == 1
    assert len(page.listeners) == 1


@pytest.mark.asyncio
async def test_wires_up_each_distinct_page_independently():
    """wires up each distinct page independently."""
    page_a = _create_mock_page()
    page_b = _create_mock_page()

    await apply_force_chrome_select_rendering(page_a)
    await apply_force_chrome_select_rendering(page_b)

    assert len(page_a.listeners) == 1
    assert len(page_b.listeners) == 1
