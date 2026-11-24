"""Synced from upstream
``packages/web-integration/tests/unit-test/bridge/file-chooser.test.ts``.

The Python Playwright page exposes the same accept/getError registration
contract used by the bridge file chooser adapter.
"""

from typing import Any
from unittest.mock import Mock

import pytest


class _FakeChooser:
    def __init__(self):
        self.files: list[str] = []

    async def set_files(self, files):
        self.files = list(files)


class _FakeBrowserPage:
    def __init__(self):
        self.handlers: dict[str, list[Any]] = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers.get(event, []).remove(handler)


def _page():
    from midscene.web_integration.playwright.page import PlaywrightWebPage

    fake = _FakeBrowserPage()
    return PlaywrightWebPage(page=fake, context=Mock(), browser=Mock()), fake


@pytest.mark.asyncio
async def test_converts_register_file_chooser_listener_into_bridge_file_accept_calls():
    page, fake = _page()
    chooser = _FakeChooser()

    async def handler(file_chooser):
        await file_chooser.accept(["/tmp/upload.txt"])

    registration = await page.register_file_chooser_listener(handler)
    await fake.handlers["filechooser"][0](chooser)
    assert chooser.files == ["/tmp/upload.txt"]
    assert registration.get_error() is None
    registration.dispose()
    assert fake.handlers.get("filechooser") == []


@pytest.mark.asyncio
async def test_polls_remote_file_chooser_errors_when_get_error_is_called():
    page, fake = _page()

    async def failing(file_chooser):
        raise RuntimeError("upload failed")

    registration = await page.register_file_chooser_listener(failing)
    await fake.handlers["filechooser"][0](_FakeChooser())
    error = registration.get_error()
    assert isinstance(error, RuntimeError)
