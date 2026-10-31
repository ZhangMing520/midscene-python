"""Real-browser checks for the Selenium primitives.

Skipped when Chrome or a matching chromedriver is unavailable. The driver is
looked up via CHROMEDRIVER, PATH, or Selenium Manager's cache directory.
"""

import glob
import os
import shutil
from urllib.parse import quote

import pytest
import pytest_asyncio

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
  window.__events = { clicks: [], down: null, up: null, moves: 0 };
  document.addEventListener('mousedown', (event) => {
    window.__events.clicks.push([event.clientX, event.clientY]);
    window.__events.down = [event.clientX, event.clientY];
  });
  document.addEventListener('mousemove', (event) => {
    window.__events.moves += 1;
  });
  document.addEventListener('mouseup', (event) => {
    window.__events.up = [event.clientX, event.clientY];
  });
</script>
"""


def _find_chromedriver():
    cached = sorted(
        glob.glob(os.path.expanduser("~/.cache/selenium/chromedriver/*/*/chromedriver")),
        reverse=True,
    )
    candidates = []
    env = os.environ.get("CHROMEDRIVER")
    if env:
        candidates.append(env)
    on_path = shutil.which("chromedriver")
    if on_path:
        candidates.append(on_path)
    candidates.extend(cached)
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


@pytest_asyncio.fixture
async def selenium_page():
    pytest.importorskip("selenium")
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    from midscene.web.selenium_page import SeleniumWebPage

    driver_path = _find_chromedriver()
    if not driver_path:
        pytest.skip("chromedriver is not available")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=800,600")
    try:
        driver = webdriver.Chrome(
            service=Service(executable_path=driver_path), options=options
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"chrome is not available: {exc}")

    driver.get("data:text/html;charset=utf-8," + quote(DEMO_PAGE))
    try:
        yield SeleniumWebPage(driver), driver
    finally:
        driver.quit()


def _events(driver):
    return driver.execute_script("return window.__events")


def _region_state(driver):
    return driver.execute_script(
        "const region = document.getElementById('region');"
        "return {"
        " top: region.scrollTop,"
        " maxTop: region.scrollHeight - region.clientHeight,"
        " windowY: window.scrollY"
        "};"
    )


@pytest.mark.asyncio
async def test_two_taps_use_absolute_coordinates(selenium_page):
    page, driver = selenium_page

    await page.tap(100, 100)
    await page.tap(300, 200)

    assert _events(driver)["clicks"] == [[100, 100], [300, 200]]


@pytest.mark.asyncio
async def test_drag_and_drop_dispatches_mouse_drag(selenium_page):
    page, driver = selenium_page

    await page.drag_and_drop((540, 140), (700, 400))

    events = _events(driver)
    assert events["down"] == [540, 140]
    assert events["up"] == [700, 400]
    assert events["moves"] >= 1


@pytest.mark.asyncio
async def test_scroll_to_bottom_uses_located_region(selenium_page):
    page, driver = selenium_page

    await page.scroll("down", scroll_type="scrollToBottom", point=(200, 160))

    state = _region_state(driver)
    assert state["top"] == state["maxTop"]
    assert state["windowY"] == 0


@pytest.mark.asyncio
async def test_single_action_scroll_uses_located_region(selenium_page):
    page, driver = selenium_page

    await page.scroll("down", distance=200, point=(200, 160))

    state = _region_state(driver)
    assert 0 < state["top"] <= 200
    assert state["windowY"] == 0


@pytest.mark.asyncio
async def test_cache_feature_roundtrip(selenium_page):
    page, driver = selenium_page

    feature = await page.cache_feature_for_point([540, 140])
    assert feature["xpaths"]

    rect = await page.rect_matches_cache_feature(feature)
    assert rect is not None
    assert round(rect.left) == 500
    assert round(rect.top) == 100
    assert round(rect.width) == 80
    assert round(rect.height) == 80


@pytest.mark.asyncio
async def test_cache_feature_uses_text_for_leaf(selenium_page):
    page, driver = selenium_page

    feature = await page.cache_feature_for_point([80, 310])
    assert any("Unique label" in xpath for xpath in feature["xpaths"])

    rect = await page.rect_matches_cache_feature(feature)
    assert rect is not None
    assert round(rect.left) == 50
    assert round(rect.top) == 300


@pytest.mark.asyncio
async def test_stale_cache_feature_returns_none(selenium_page):
    page, driver = selenium_page

    rect = await page.rect_matches_cache_feature(
        {"xpaths": ["//*[@id='missing-element']"]}
    )
    assert rect is None


@pytest.mark.asyncio
async def test_cache_feature_skips_iframe(selenium_page):
    page, driver = selenium_page

    driver.get(
        "data:text/html;charset=utf-8,"
        + quote(
            "<style>body{margin:0}</style>"
            "<iframe style='position:absolute;left:100px;top:100px;"
            "width:200px;height:150px;border:0' "
            "srcdoc=\"<button style='width:100%;height:100%'>inner</button>\"></iframe>"
        )
    )

    feature = await page.cache_feature_for_point([200, 175])
    assert feature["xpaths"] == []


@pytest.mark.asyncio
async def test_cache_feature_skips_shadow_dom(selenium_page):
    page, driver = selenium_page

    driver.get(
        "data:text/html;charset=utf-8,"
        + quote(
            "<style>body{margin:0}</style>"
            "<div id='host' style='position:absolute;left:50px;top:50px;"
            "width:200px;height:100px'></div>"
            "<script>"
            "document.getElementById('host').attachShadow({mode: 'open'}).innerHTML ="
            "'<button style=\"width:100%;height:100%\">shadow button</button>';"
            "</script>"
        )
    )

    feature = await page.cache_feature_for_point([150, 100])
    assert feature["xpaths"] == []
