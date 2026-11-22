"""Port of upstream
packages/web-integration/tests/ai/web/puppeteer/iframe-xpath.test.ts.

The upstream cases use a Puppeteer agent and an AI model for the locate cases.
Only the cache-feature cases are ported here, driven through the Playwright
page against an inline same-origin iframe.
"""

import pytest
import pytest_asyncio

pytest.importorskip("playwright.async_api")

_IFRAME_PAGE = """
<style>body { margin: 0; }</style>
<iframe
  id="test-iframe"
  style="position:absolute;left:100px;top:100px;width:400px;height:200px;border:0"
  srcdoc="<style>body { margin: 0; }</style>
          <button id='inner-btn'
            style='position:absolute;left:20px;top:50px;width:120px;height:60px'
          >Submit Order</button>"
></iframe>
"""

_IFRAME_LEFT = 100
_IFRAME_TOP = 100
# Point inside the button: iframe origin + button offset + half the button size.
_POINT = [_IFRAME_LEFT + 20 + 60, _IFRAME_TOP + 50 + 30]


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
        await page.set_content(_IFRAME_PAGE)
        await page.wait_for_timeout(100)
        try:
            yield PlaywrightWebPage(page, None, None), page
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_cache_feature_for_point_should_return_compound_xpath_for_point_inside_iframe(
    web_page,
):
    web, page = web_page

    feature = await web.cache_feature_for_point(_POINT)

    assert feature is not None
    assert feature.get("xpaths") is not None
    assert len(feature["xpaths"]) > 0
    # Should contain compound xpath with |>>| for iframe element
    assert "|>>|" in feature["xpaths"][0]
    assert "iframe" in feature["xpaths"][0]


@pytest.mark.asyncio
async def test_rect_matches_cache_feature_should_resolve_compound_xpath_and_return_valid_rect(
    web_page,
):
    web, page = web_page

    feature = await web.cache_feature_for_point(_POINT)
    assert "|>>|" in feature["xpaths"][0]

    rect = await web.rect_matches_cache_feature(feature)

    assert rect is not None
    assert rect.width > 0
    assert rect.height > 0
    # Rect should be within the iframe area
    assert rect.left >= _IFRAME_LEFT
    assert rect.top >= _IFRAME_TOP


@pytest.mark.asyncio
async def test_rect_matches_cache_feature_should_throw_for_invalid_compound_xpath(
    web_page,
):
    web, page = web_page

    with pytest.raises(Exception):
        await web.rect_matches_cache_feature(
            {"xpaths": ["/html/body/iframe[99]|>>|/html/body/button[1]"]}
        )
