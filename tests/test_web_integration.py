"""Real-browser checks for the web scroll and drag primitives.

Skipped when Playwright or its Chromium build is unavailable.
"""

import pytest
import pytest_asyncio

pytest.importorskip("playwright.async_api")

DEMO_PAGE = """
<style>
  body { margin: 0; }
  #region {
    position: absolute; left: 50px; top: 60px;
    width: 300px; height: 200px;
    overflow: auto; border: 1px solid #000;
  }
  #region-inner { width: 2000px; height: 2000px; }
  #card {
    position: absolute; left: 500px; top: 100px;
    width: 80px; height: 80px; background: #c00;
  }
</style>
<div id="region"><div id="region-inner"></div></div>
<div id="card"></div>
<script>
  window.__drag = { down: null, up: null, moves: 0 };
  document.getElementById('card').addEventListener('mousedown', (event) => {
    window.__drag.down = [event.clientX, event.clientY];
  });
  document.addEventListener('mousemove', (event) => {
    window.__drag.moves += 1;
    window.__drag.last = [event.clientX, event.clientY];
  });
  document.addEventListener('mouseup', (event) => {
    window.__drag.up = [event.clientX, event.clientY];
  });
</script>
"""


@pytest_asyncio.fixture
async def web_page():
    from playwright.async_api import async_playwright

    from midscene.web.playwright_page import PlaywrightWebPage

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"chromium is not available: {exc}")
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        await page.set_content(DEMO_PAGE)
        try:
            yield PlaywrightWebPage(page, None, None), page
        finally:
            await browser.close()


async def _region_state(page):
    return await page.evaluate(
        """() => {
          const region = document.getElementById('region');
          return {
            top: region.scrollTop,
            left: region.scrollLeft,
            maxTop: region.scrollHeight - region.clientHeight,
            windowY: window.scrollY,
          };
        }"""
    )


@pytest.mark.asyncio
async def test_scroll_to_bottom_uses_located_region(web_page):
    web, page = web_page

    await web.scroll("down", scroll_type="scrollToBottom", point=(200, 160))

    state = await _region_state(page)
    assert state["top"] == state["maxTop"]
    assert state["windowY"] == 0


@pytest.mark.asyncio
async def test_single_action_scroll_uses_located_region(web_page):
    web, page = web_page

    await web.scroll("down", distance=200, point=(200, 160))

    state = await _region_state(page)
    assert 0 < state["top"] <= 200
    assert state["windowY"] == 0


@pytest.mark.asyncio
async def test_drag_and_drop_dispatches_mouse_drag(web_page):
    web, page = web_page

    await web.drag_and_drop((540, 140), (700, 400))

    drag = await page.evaluate("window.__drag")
    assert drag["down"] == [540, 140]
    assert drag["up"] == [700, 400]
    assert drag["moves"] >= 1
