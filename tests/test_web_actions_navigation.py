"""Synced from upstream
``packages/web-integration/tests/unit-test/web-actions-navigation.test.ts``.

The Python Playwright page keeps the upstream text-input strategy contract:
bulk input uses one insertText call, sequential input types code points
individually, and the legacy strategy forwards the platform keyboard delay.
"""

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest


class _FakeKeyboard:
    def __init__(self):
        self.typed: List[tuple] = []
        self.inserted: List[str] = []
        self.presses: List[str] = []

    async def type(self, text, **kwargs):
        self.typed.append((text, kwargs.get("delay")))

    async def insert_text(self, text):
        self.inserted.append(text)

    async def press(self, key):
        self.presses.append(key)


class _FakeTypingPage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()
        self.handlers: Dict[str, Any] = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def remove_listener(self, event, handler):
        self.handlers.pop(event, None)


def test_rejects_an_unsupported_runtime_strategy_before_typing():
    from midscene.web_integration.playwright.page import _resolve_text_input_options

    with pytest.raises(ValueError, match="non-negative"):
        _resolve_text_input_options(None, -1)
    with pytest.raises(ValueError, match="must be one of"):
        _resolve_text_input_options("typo", None)
    with pytest.raises(ValueError, match='"bulk" requires'):
        _resolve_text_input_options("bulk", 10)


@pytest.mark.asyncio
async def test_uses_the_page_level_bulk_strategy_when_the_action_omits_it():
    from midscene.web_integration.playwright.page import PlaywrightWebPage

    web = PlaywrightWebPage(_FakeTypingPage(), Mock(), Mock())
    await web.input_text("hello", input_strategy="bulk")
    assert web.page.keyboard.inserted == ["hello"]
    assert web.page.keyboard.typed == []


@pytest.mark.asyncio
async def test_sends_unicode_code_points_separately_for_sequential_input():
    from midscene.web_integration.playwright.page import PlaywrightWebPage

    web = PlaywrightWebPage(_FakeTypingPage(), Mock(), Mock())
    await web.input_text("ab", input_strategy="sequential", keyboard_type_delay=0)
    assert web.page.keyboard.typed == [("a", 0), ("b", 0)]


@pytest.mark.asyncio
async def test_passes_action_level_keyboard_type_delay_to_text_input_actions():
    from midscene.web_integration.playwright.page import PlaywrightWebPage

    web = PlaywrightWebPage(
        _FakeTypingPage(), Mock(), Mock(), keyboard_type_delay=25
    )
    await web.input_text("hi")
    assert web.page.keyboard.typed == [("hi", 25)]


@pytest.mark.asyncio
async def test_selects_existing_text_without_clearing_before_bulk_replace_input():
    from midscene.web_integration.playwright.page import PlaywrightWebPage

    web = PlaywrightWebPage(_FakeTypingPage(), Mock(), Mock())
    await web.replace_input("next", input_strategy="bulk")
    assert web.page.keyboard.presses == ["Control+A"]
    assert web.page.keyboard.inserted == ["next"]


class _FakeMouse:
    def __init__(self):
        self.clicks: List[tuple] = []
        self.moves: List[tuple] = []
        self.wheels: List[tuple] = []

    async def click(self, x, y, **kwargs):
        self.clicks.append((x, y, kwargs))

    async def move(self, x, y):
        self.moves.append((x, y))

    async def wheel(self, delta_x, delta_y):
        self.wheels.append((delta_x, delta_y))


class _ActionFakePage:
    def __init__(self):
        self.mouse = _FakeMouse()
        self.keyboard = _FakeKeyboard()
        self.scheduled: List[bool] = []
        self.flushed: List[bool] = []

    def schedule_pending_visual_update(self, force=False):
        self.scheduled.append(force)

    async def flush_pending_visual_update(self, force=False):
        self.flushed.append(force)

    async def size(self):
        return {"width": 1280, "height": 720}


def _find_action(actions, name):
    return next(action for action in actions if action.name == name)


class TestCommonWebActionsForWebPageNavigation:
    def test_supports_system_one_for_simple_navigation_but_delegates_url_generation(self):
        """supports System One for simple navigation but delegates URL generation"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        actions = common_web_actions_for_web_page({})

        for name in ("Reload", "GoBack", "GoForward"):
            assert _find_action(actions, name).supported_by_system_one is True
        assert (
            _find_action(actions, "Navigate").supported_by_system_one is False
        )

    @pytest.mark.asyncio
    async def test_exposes_forward_without_exposing_stop_as_an_action_space_entry(self):
        """exposes forward without exposing stop as an action-space entry"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        calls: List[str] = []

        class Page(_ActionFakePage):
            async def go_forward(self):
                calls.append("goForward")

            async def stop_loading(self):
                calls.append("stopLoading")

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "GoForward").execute(None)

        assert calls == ["goForward"]
        assert not any(action.name == "Stop" for action in actions)


class TestCommonWebActionsForWebPageVisualRefresh:
    @pytest.mark.asyncio
    async def test_schedules_the_preview_refresh_after_tap_actions(self):
        """schedules the preview refresh after tap actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Tap").execute(
            {"locate": {"center": [10, 20]}}
        )

        assert page.mouse.clicks == [(10, 20, {"button": "left"})]
        assert page.scheduled == [False]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_schedules_the_preview_refresh_after_keyboard_only_actions(self):
        """schedules the preview refresh after keyboard-only actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "KeyboardPress").execute(
            {"keyName": "Meta+A"}
        )

        assert len(page.keyboard.presses) == 1
        assert page.scheduled == [False]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_schedules_the_preview_refresh_after_text_input_actions(self):
        """schedules the preview refresh after text input actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {"value": "hello", "mode": "typeOnly"}
        )

        assert page.keyboard.typed == [("hello", None)]
        assert page.scheduled == [False]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_schedules_the_preview_refresh_after_scroll_actions(self):
        """schedules the preview refresh after scroll actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        scrolls: List[tuple] = []

        class Page(_ActionFakePage):
            async def scroll(self, direction, distance=None, **kwargs):
                scrolls.append((direction, distance, kwargs))

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Scroll").execute(
            {"direction": "down", "scrollType": "singleAction"}
        )

        assert len(scrolls) == 1
        assert scrolls[0][0] == "down"
        assert page.scheduled == [False]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_schedules_the_preview_refresh_after_navigation_actions(self):
        """schedules the preview refresh after navigation actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        navigations: List[str] = []

        class Page(_ActionFakePage):
            async def navigate(self, url):
                navigations.append(url)

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Navigate").execute(
            {"url": "https://example.com"}
        )

        assert navigations == ["https://example.com"]
        assert page.scheduled == [True]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_force_refreshes_the_preview_after_reload_actions(self):
        """force-refreshes the preview after reload actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        reloads: List[int] = []

        class Page(_ActionFakePage):
            async def reload(self):
                reloads.append(1)

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Reload").execute(None)

        assert reloads == [1]
        assert page.scheduled == [True]
        assert page.flushed == []

    @pytest.mark.asyncio
    async def test_passes_action_level_keyboard_type_delay_to_text_input_actions(self):
        """passes action-level keyboardTypeDelay to text input actions"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {
                "value": "hello",
                "mode": "typeOnly",
                "keyboardTypeDelay": 25,
            }
        )

        assert page.keyboard.typed == [("hello", 25)]

    @pytest.mark.asyncio
    async def test_uses_the_page_level_bulk_strategy_when_the_action_omits_it(self):
        """uses the page-level bulk strategy when the action omits it"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        page.input_strategy = "bulk"
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {"value": "北京", "mode": "typeOnly"}
        )

        assert page.keyboard.inserted == ["北京"]
        assert page.keyboard.typed == []

    @pytest.mark.asyncio
    async def test_sends_unicode_code_points_separately_for_sequential_input(self):
        """sends Unicode code points separately for sequential input"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {
                "value": "A😀B",
                "mode": "typeOnly",
                "inputStrategy": "sequential",
            }
        )

        assert page.keyboard.typed == [
            ("A", 0),
            ("😀", 0),
            ("B", 0),
        ]
        assert page.keyboard.inserted == []

    @pytest.mark.asyncio
    async def test_lets_action_level_zero_disable_the_page_level_keyboard_delay(self):
        """lets action-level zero disable the page-level keyboard delay"""
        from midscene.web_integration.playwright.page import PlaywrightWebPage
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        type_calls: List[tuple] = []

        class Keyboard:
            async def type(self, text, delay=None):
                type_calls.append((text, delay))

        class Page(PlaywrightWebPage):
            def __init__(self):
                self.keyboard = Keyboard()
                self.keyboard_type_delay = 80
                self.input_strategy = None

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {
                "value": "AB",
                "mode": "typeOnly",
                "inputStrategy": "sequential",
                "keyboardTypeDelay": 0,
            }
        )

        assert type_calls == [("A", 0), ("B", 0)]

    @pytest.mark.asyncio
    async def test_rejects_an_unsupported_runtime_strategy_before_typing(self):
        """rejects an unsupported runtime strategy before typing"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        actions = common_web_actions_for_web_page(page)

        with pytest.raises(
            ValueError,
            match="inputStrategy must be one of: legacy, sequential, bulk; "
            "received paste",
        ):
            await _find_action(actions, "Input").execute(
                {
                    "value": "hello",
                    "mode": "typeOnly",
                    "inputStrategy": "paste",
                }
            )
        assert page.keyboard.typed == []
        assert page.keyboard.inserted == []

    @pytest.mark.asyncio
    async def test_selects_existing_text_without_clearing_before_bulk_replace_input(self):
        """selects existing text without clearing before bulk replace input"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        locate = {"center": [10, 20]}

        class Page(_ActionFakePage):
            def __init__(self):
                super().__init__()
                self.selected: List[Any] = []
                self.cleared: List[Any] = []
                self.waited: List[Any] = []

            async def select_all_input(self, element=None):
                self.selected.append(element)

            async def clear_input(self, element=None):
                self.cleared.append(element)

            async def wait_for_dom_quiet(self, options=None):
                self.waited.append(options)

        page = Page()
        actions = common_web_actions_for_web_page(page)

        await _find_action(actions, "Input").execute(
            {
                "value": "上海",
                "mode": "replace",
                "inputStrategy": "bulk",
                "locate": locate,
            }
        )

        assert page.selected == [locate]
        assert page.keyboard.inserted == ["上海"]
        assert page.cleared == []
        assert page.waited == []

    @pytest.mark.asyncio
    async def test_rejects_bulk_input_with_a_configured_positive_keyboard_delay(self):
        """rejects bulk input with a configured positive keyboard delay"""
        from midscene.web_integration.web_page import (
            common_web_actions_for_web_page,
        )

        page = _ActionFakePage()
        page.keyboard_type_delay = 25
        actions = common_web_actions_for_web_page(page)

        with pytest.raises(
            ValueError,
            match='inputStrategy "bulk" requires keyboardTypeDelay to be '
            'omitted or set to 0; use inputStrategy "sequential" for delayed '
            "input",
        ):
            await _find_action(actions, "Input").execute(
                {
                    "value": "hello",
                    "mode": "typeOnly",
                    "inputStrategy": "bulk",
                }
            )
