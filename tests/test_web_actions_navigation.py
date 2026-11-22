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
