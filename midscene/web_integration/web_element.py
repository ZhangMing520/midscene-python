"""Web element wrapper (upstream web-integration/web-element.ts)."""

from loguru import logger
from playwright.async_api import Page

from midscene.core.types import BaseElement


class PlaywrightElement(BaseElement):
    """Playwright element wrapper."""

    def __init__(self, page: Page, selector: str, **kwargs):
        self._page = page
        self._selector = selector
        super().__init__(**kwargs)

    async def tap(self) -> None:
        """Click this element."""
        try:
            await self._page.click(self._selector)
        except Exception as e:
            logger.error(f"Failed to click element: {e}")
            raise

    async def input_text(self, text: str) -> None:
        """Input text to this element."""
        try:
            await self._page.fill(self._selector, text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise


__all__ = ["PlaywrightElement"]
