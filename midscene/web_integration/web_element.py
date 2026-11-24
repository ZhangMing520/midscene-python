"""Web element wrapper (upstream web-integration/web-element.ts)."""

import math
from typing import Any

from loguru import logger
from playwright.async_api import Page

from midscene.core.types import BaseElement, NodeType, Rect

# Exact injected script that keeps target=_blank navigation in the current tab
# (upstream web-element.ts limitOpenNewTabScript).
LIMIT_OPEN_NEW_TAB_SCRIPT = """
if (!window.__MIDSCENE_NEW_TAB_INTERCEPTOR_INITIALIZED__) {
  window.__MIDSCENE_NEW_TAB_INTERCEPTOR_INITIALIZED__ = true;

  // Intercept the window.open method (only once)
  window.open = function(url) {
    console.log('Blocked window.open:', url);
    window.location.href = url;
    return null;
  };

  // Block all a tag clicks with target="_blank" (only once)
  document.addEventListener('click', function(e) {
    const target = e.target.closest('a');
    if (target && target.target === '_blank') {
      e.preventDefault();
      console.log('Blocked new tab:', target.href);
      window.location.href = target.href;
      target.removeAttribute('target');
    }
  }, true);
}
"""


class WebElementInfoImpl(BaseElement):
    """Upstream WebElementInfoImpl: BaseElement with an ``indexId`` and a
    computed floating-point center."""

    index_id: int = 0

    def __init__(
        self,
        *,
        content: str,
        rect: Rect,
        id: str,
        attributes: dict[str, Any],
        index_id: int,
        xpaths: list[str] | None = None,
        is_visible: bool,
    ):
        node_type = attributes.get("nodeType") or attributes.get("node_type")
        if isinstance(node_type, str):
            try:
                node_type = NodeType(node_type)
            except ValueError:
                node_type = NodeType.OTHER
        if not isinstance(node_type, NodeType):
            node_type = NodeType.OTHER

        extra_fields: dict[str, Any] = {"index_id": index_id}
        super().__init__(
            id=id,
            content=content,
            rect=rect,
            center=(
                math.floor(rect.left + rect.width / 2),
                math.floor(rect.top + rect.height / 2),
            ),
            node_type=node_type,
            attributes=attributes,
            is_visible=is_visible,
            xpaths=xpaths,
            **extra_fields,
        )


class PlaywrightElement(BaseElement):
    """Playwright element wrapper."""

    def __init__(self, page: Page, selector: str, **kwargs: Any) -> None:
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


__all__ = [
    "LIMIT_OPEN_NEW_TAB_SCRIPT",
    "PlaywrightElement",
    "WebElementInfoImpl",
]
