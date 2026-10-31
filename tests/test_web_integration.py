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
  #label {
    position: absolute; left: 50px; top: 300px;
    width: 200px; height: 30px;
  }
</style>
<div id="region"><div id="region-inner"></div></div>
<div id="card"></div>
<div id="label">Unique label</div>
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


@pytest.mark.asyncio
async def test_cache_feature_roundtrip(web_page):
    web, page = web_page

    feature = await web.cache_feature_for_point([540, 140])
    assert feature["xpaths"]

    rect = await web.rect_matches_cache_feature(feature)
    assert rect is not None
    assert round(rect.left) == 500
    assert round(rect.top) == 100
    assert round(rect.width) == 80
    assert round(rect.height) == 80


@pytest.mark.asyncio
async def test_cache_feature_uses_text_for_leaf(web_page):
    web, page = web_page

    feature = await web.cache_feature_for_point([80, 310])
    assert any("Unique label" in xpath for xpath in feature["xpaths"])

    rect = await web.rect_matches_cache_feature(feature)
    assert rect is not None
    assert round(rect.left) == 50
    assert round(rect.top) == 300


@pytest.mark.asyncio
async def test_stale_cache_feature_returns_none(web_page):
    web, page = web_page

    rect = await web.rect_matches_cache_feature(
        {"xpaths": ["//*[@id='missing-element']"]}
    )
    assert rect is None


@pytest.mark.asyncio
async def test_cache_feature_skips_iframe(web_page):
    web, page = web_page

    await page.set_content(
        "<style>body{margin:0}</style>"
        "<iframe style='position:absolute;left:100px;top:100px;"
        "width:200px;height:150px;border:0' "
        "srcdoc=\"<button style='width:100%;height:100%'>inner</button>\"></iframe>"
    )
    await page.wait_for_timeout(100)

    feature = await web.cache_feature_for_point([200, 175])
    assert feature["xpaths"] == []


@pytest.mark.asyncio
async def test_cache_feature_skips_shadow_dom(web_page):
    web, page = web_page

    await page.set_content(
        "<style>body{margin:0}</style>"
        "<div id='host' style='position:absolute;left:50px;top:50px;"
        "width:200px;height:100px'></div>"
        "<script>"
        "document.getElementById('host').attachShadow({mode: 'open'}).innerHTML ="
        "'<button style=\"width:100%;height:100%\">shadow button</button>';"
        "</script>"
    )
    await page.wait_for_timeout(100)

    feature = await web.cache_feature_for_point([150, 100])
    assert feature["xpaths"] == []


@pytest.mark.asyncio
async def test_agent_resolves_locate_cache_without_ai(web_page, tmp_path, monkeypatch):
    from midscene.core.agent import Agent
    from midscene.core.task_cache import TaskCache
    from midscene.core.types import AgentOptions

    monkeypatch.setenv("MIDSCENE_RUN_DIR", str(tmp_path))
    web, page = web_page
    feature = await web.cache_feature_for_point([540, 140])
    TaskCache(cache_id="web-locate-e2e", enabled=True).append_locate_cache(
        "the red card", feature
    )

    agent = Agent(web, AgentOptions(cache_id="web-locate-e2e"))

    async def fail_locate(*args, **kwargs):
        raise AssertionError("AI locate must not run on a cache hit")

    monkeypatch.setattr(agent, "_run_locate", fail_locate)
    result = await agent._locate_for_action({"prompt": "the red card"})

    assert round(result["center"][0]) == 540
    assert round(result["center"][1]) == 140
