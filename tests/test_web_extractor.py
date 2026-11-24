"""Port of upstream
packages/web-integration/tests/unit-test/web-extractor.test.ts.

The upstream suite loads a fixture page over a local HTTP server and drives
``midscene_element_inspector``. The Python port implements the same xpath
extraction as an inline script (``_XPATHS_AT_POINT_JS``), so the locator
integration cases below exercise that script against an equivalent inline
page. Cases that require the Node-only extractor helpers are not ported.
"""

import pytest
import pytest_asyncio

pytest.importorskip("playwright.async_api")

# A button at (0, 350)-(200, 450): upstream targets {left: 100, top: 400}.
_DEMO_PAGE = """
<style>body { margin: 0; }</style>
<button
  id="target"
  style="position:absolute;left:0;top:350px;width:200px;height:100px"
>Submit</button>
"""


@pytest_asyncio.fixture
async def web_page():
    from playwright.async_api import async_playwright

    from midscene.web_integration.playwright.page import PlaywrightWebPage

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"chromium is not available: {exc}")
        page = await browser.new_page(viewport={"width": 1080, "height": 800})
        await page.set_content(_DEMO_PAGE)
        try:
            yield PlaywrightWebPage(page, None, None), page
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_get_xpaths_by_point_should_work_with_order_sensitive_and_order_insensitive_modes(
    web_page,
):
    from midscene.web_integration.common.browser_page_actions import (
        _XPATHS_AT_POINT_JS,
    )

    web, page = web_page

    order_sensitive_xpaths = await page.evaluate(_XPATHS_AT_POINT_JS, [100, 400, True])
    order_insensitive_xpaths = await page.evaluate(
        _XPATHS_AT_POINT_JS, [100, 400, False]
    )

    assert order_sensitive_xpaths is not None
    assert order_insensitive_xpaths is not None
    assert len(order_sensitive_xpaths) == 1
    assert len(order_insensitive_xpaths) == 1

    # Order sensitive should end with [number]
    import re

    assert re.search(r"\[\d+\]$", order_sensitive_xpaths[0])

    # Order insensitive should not end with [number] (text matching instead)
    assert not re.search(r"\[\d+\]$", order_insensitive_xpaths[0])

    # Should be different
    assert order_sensitive_xpaths[0] != order_insensitive_xpaths[0]


@pytest.mark.asyncio
async def test_cache_feature_for_point_should_work_correctly(web_page):
    web, page = web_page

    cache_feature = await web.cache_feature_for_point([100, 400])

    assert cache_feature is not None
    xpaths = cache_feature.get("xpaths")
    assert xpaths is not None
    assert len(xpaths) > 0
    assert xpaths[0].startswith("/html")
