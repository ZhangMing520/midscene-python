"""Focused tests for the upstream-aligned web-integration common modules."""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.core.types import InterfaceType
from midscene.web_integration.agent_init_args import (
    adapt_web_agent_init_args,
    adapt_web_cdp_agent_init_args,
    get_agent_init_args,
)
from midscene.web_integration.common.browser_agent import (
    BrowserAgent,
    BrowserPageManager,
    BrowserAgentRuntimeOptions,
    WebAgentCore,
    resolve_browser_agent_runtime_options,
)
from midscene.web_integration.common.browser_agent_utils import (
    apply_force_chrome_select_rendering,
    get_page_size,
    is_retryable_browser_navigation_error,
    take_screenshot_base64,
)
from midscene.web_integration.common.browser_page_actions import (
    BrowserPageActionsMixin,
    _resolve_text_input_options,
    _truncate_feedback_value,
    append_browser_agent_page_actions,
    create_browser_agent_page_actions,
)


class _Keyboard:
    def __init__(self):
        self.typed = []
        self.inserted = []
        self.presses = []

    async def type(self, text, **kwargs):
        self.typed.append((text, kwargs.get("delay")))

    async def insert_text(self, text):
        self.inserted.append(text)

    async def press(self, key):
        self.presses.append(key)


class _Mouse:
    def __init__(self):
        self.calls = []

    async def move(self, *args, **kwargs):
        self.calls.append(("move", args, kwargs))

    async def wheel(self, *args):
        self.calls.append(("wheel", args, {}))

    async def down(self):
        self.calls.append(("down", (), {}))

    async def up(self):
        self.calls.append(("up", (), {}))


class _Page:
    def __init__(self):
        self.keyboard = _Keyboard()
        self.mouse = _Mouse()
        self.viewport_size = {"width": 1000, "height": 800}
        self.evaluated = []

    async def evaluate(self, script, arg=None):
        self.evaluated.append((script, arg))
        return None

    async def screenshot(self, type="png"):
        assert type == "png"
        return b"png-bytes"


class _Actions(BrowserPageActionsMixin):
    def __init__(self):
        self.page = _Page()
        self.context = None
        self.keyboard_type_delay = None
        self.input_strategy = None


def test_playwright_page_uses_shared_actions_mixin():
    from midscene.web_integration.playwright import page as page_module

    assert issubclass(page_module.PlaywrightWebPage, BrowserPageActionsMixin)
    assert (
        page_module.PlaywrightWebPage.input_text
        is BrowserPageActionsMixin.input_text
    )
    # Old import paths keep working for callers (and existing tests).
    assert page_module._resolve_text_input_options is _resolve_text_input_options


def test_resolve_text_input_options_validates():
    assert _resolve_text_input_options(None, None) == ("legacy", None)
    assert _resolve_text_input_options("bulk", 0) == ("bulk", 0.0)
    with pytest.raises(ValueError, match="non-negative"):
        _resolve_text_input_options(None, -1)
    with pytest.raises(ValueError, match="must be one of"):
        _resolve_text_input_options("typo", None)
    with pytest.raises(ValueError, match='"bulk" requires'):
        _resolve_text_input_options("bulk", 10)


@pytest.mark.asyncio
async def test_mixin_input_and_scroll_use_page_primitives():
    actions = _Actions()
    await actions.input_text("hello", input_strategy="bulk")
    assert actions.page.keyboard.inserted == ["hello"]

    with patch(
        "midscene.web_integration.common.browser_page_actions.asyncio.sleep",
        AsyncMock(),
    ):
        await actions.scroll("down")
    assert actions.page.evaluated == []


def test_retryable_navigation_error_predicate():
    assert is_retryable_browser_navigation_error(
        RuntimeError("Execution context was destroyed")
    )
    assert is_retryable_browser_navigation_error(RuntimeError("Target closed"))
    assert not is_retryable_browser_navigation_error(ValueError("boom"))


@pytest.mark.asyncio
async def test_force_chrome_select_rendering_disabled_is_noop():
    page = _Page()
    await apply_force_chrome_select_rendering(page, enabled=False)
    assert page.evaluated == []


@pytest.mark.asyncio
async def test_force_chrome_select_rendering_patches_page():
    page = _Page()
    calls = []

    async def add_init_script(script):
        calls.append(script)

    page.add_init_script = add_init_script
    with patch(
        "midscene.web_integration.common.browser_agent_utils._get_package_version",
        return_value="1.60.0",
    ):
        await apply_force_chrome_select_rendering(page, enabled=True)

    assert len(calls) == 1
    assert "midscene-force-select-rendering" in calls[0]
    assert len(page.evaluated) == 1


@pytest.mark.asyncio
async def test_screenshot_and_page_size_helpers():
    page = _Page()

    async def evaluate(script):
        return {"width": 640, "height": 480}

    page.evaluate = evaluate
    assert await take_screenshot_base64(page) == base64.b64encode(
        b"png-bytes"
    ).decode()
    size = await get_page_size(page)
    assert (size.width, size.height) == (640, 480)


def test_resolve_browser_agent_runtime_options():
    page_scope = resolve_browser_agent_runtime_options(
        BrowserAgentRuntimeOptions(agent_name="web", page_scope="page")
    )
    assert page_scope.force_same_tab_navigation is True
    assert page_scope.auto_follow_new_page is False

    browser_scope = resolve_browser_agent_runtime_options(
        {
            "agent_name": "web",
            "page_scope": "browser",
            "auto_follow_new_page": True,
            "new_page_timeout": 2000,
        }
    )
    assert browser_scope.force_same_tab_navigation is False
    assert browser_scope.auto_follow_new_page is True
    assert browser_scope.new_page_timeout == 2000

    with pytest.raises(ValueError, match="requires browser mode"):
        resolve_browser_agent_runtime_options(
            {"agent_name": "web", "page_scope": "page", "auto_follow_new_page": True}
        )
    with pytest.raises(ValueError, match="cannot be used in browser mode"):
        resolve_browser_agent_runtime_options(
            {
                "agent_name": "web",
                "page_scope": "browser",
                "force_same_tab_navigation": True,
            }
        )


class _FakeTab:
    def __init__(self, title, url):
        self.title = title
        self.url = url
        self.closed = False
        self.fronted = False


class _FakeAdapter:
    def __init__(self, pages):
        self.open_pages = pages
        self.handlers = []
        self.new_event = None

    def pages(self):
        return self.open_pages

    def is_page_closed(self, page):
        return page.closed

    def bring_to_front(self, page):
        page.fronted = True

    def page_title(self, page):
        return page.title

    def page_url(self, page):
        return page.url

    def on_new_page(self, handler):
        self.handlers.append(handler)

    def off_new_page(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def resolve_new_page(self, event):
        return event

    def is_new_page_event(self, event):
        return True

    def trigger(self, event):
        for handler in list(self.handlers):
            result = handler(event)
            if hasattr(result, "__await__"):
                import asyncio

                asyncio.get_running_loop().create_task(result)


@pytest.mark.asyncio
async def test_browser_page_manager_summaries_and_selection():
    first = _FakeTab("First tab", "https://a.example")
    second = _FakeTab("Second", "https://b.example")
    adapter = _FakeAdapter([first, second])
    active = {"page": first}
    manager = BrowserPageManager(
        agent_name="web",
        adapter=adapter,
        get_active_page=lambda: active["page"],
        set_active_page=lambda page: active.__setitem__("page", page),
    )

    summaries = await manager.page_summaries()
    assert [(item["index"], item["active"]) for item in summaries] == [
        (0, True),
        (1, False),
    ]

    summary = await manager.set_active_page_by_selector({"title": "second"})
    assert summary["index"] == 1
    assert active["page"] is second
    assert second.fronted is True

    with pytest.raises(ValueError, match="Cannot find"):
        await manager.page_summary_by_index(9)
    with pytest.raises(ValueError, match="requires index, title, or url"):
        await manager.set_active_page_by_selector({})

    first.closed = True
    with pytest.raises(ValueError, match="Cannot find"):
        await manager.set_active_page_by_selector({"index": 1})


@pytest.mark.asyncio
async def test_browser_page_manager_waits_for_new_page():
    first = _FakeTab("First", "https://a.example")
    adapter = _FakeAdapter([first])
    active = {"page": first}
    manager = BrowserPageManager(
        agent_name="web",
        adapter=adapter,
        get_active_page=lambda: active["page"],
        set_active_page=lambda page: active.__setitem__("page", page),
    )
    new_tab = _FakeTab("New", "https://new.example")

    async def action():
        adapter.trigger(new_tab)

    page = await manager.wait_for_new_page(action, {"timeout": 1000})
    assert page is new_tab


def test_browser_agent_is_thin_core_agent():
    assert issubclass(BrowserAgent, WebAgentCore)
    assert issubclass(WebAgentCore, Agent)


def test_adapt_web_agent_init_args_filters_unknown_keys():
    args = adapt_web_agent_init_args(
        {
            "url": "https://example.com",
            "aiContexts": {"default": "be brief", "bogus": "drop"},
            "aiActContext": "act context",
            "replanningCycleLimit": 3,
            "waitAfterAction": 10,
            "screenshotShrinkFactor": 2,
            "unknown": "drop",
        }
    )
    assert args == {
        "url": "https://example.com",
        "aiContexts": {"default": "be brief"},
        "aiActContext": "act context",
        "replanningCycleLimit": 3,
        "waitAfterAction": 10,
        "screenshotShrinkFactor": 2,
    }
    assert get_agent_init_args(args) == args
    assert adapt_web_agent_init_args(None) is None
    assert adapt_web_agent_init_args({"unknown": 1}) is None


def test_adapt_web_cdp_agent_init_args_parses_headers():
    args = adapt_web_cdp_agent_init_args(
        {
            "url": "https://example.com",
            "extraHttpHeader": ["X-One: 1", "X-Two:  two "],
        }
    )
    assert args["extraHTTPHeaders"] == {"X-One": "1", "X-Two": "two"}

    single = adapt_web_cdp_agent_init_args({"extraHttpHeader": "X-One: 1"})
    assert single["extraHTTPHeaders"] == {"X-One": "1"}

    with pytest.raises(ValueError, match="Name:Value"):
        adapt_web_cdp_agent_init_args({"extraHttpHeader": "missing-colon"})
    with pytest.raises(ValueError, match="Name:Value"):
        adapt_web_cdp_agent_init_args({"extraHttpHeader": []})


def test_config_factory_uses_web_agent_init_args():
    from midscene.cli.config_factory import _build_agent_options

    options = _build_agent_options(
        {
            "agent": {
                "groupName": "web run",
                "aiContexts": {"default": "short answers"},
                "replanningCycleLimit": 4,
                "waitAfterAction": 50,
                "screenshotShrinkFactor": 2,
            }
        }
    )
    assert options.group_name == "web run"
    assert options.ai_contexts == {"default": "short answers"}
    assert options.replanning_cycle_limit == 4
    assert options.wait_after_action_ms == 50
    assert options.screenshot_shrink_factor == 2

    defaults = _build_agent_options({})
    assert defaults.group_name == "Midscene Report"
    assert defaults.ai_contexts is None
    assert defaults.replanning_cycle_limit is None
    assert defaults.wait_after_action_ms == 300
    assert defaults.screenshot_shrink_factor == 1.0


class _FakeBridgePage:
    interface_type = InterfaceType.WEB

    def __init__(self):
        self.status_messages = []
        self.new_tab_calls = []
        self.current_tab_calls = []
        self.water_flow_calls = []
        self.destroy_options = []
        self.active_tab_ids = []
        self.closed = False

    async def show_status_message(self, message):
        self.status_messages.append(message)

    async def connect_new_tab_with_url(self, url, options=None):
        self.new_tab_calls.append((url, options))

    async def connect_current_tab(self, options=None):
        self.current_tab_calls.append(options)

    async def set_water_flow_animation_enabled(self, enabled):
        self.water_flow_calls.append(enabled)

    async def set_destroy_options(self, options):
        self.destroy_options.append(options)

    async def get_browser_tab_list(self):
        return [{"id": 1, "title": "tab", "url": "https://example.com"}]

    async def set_active_tab_id(self, tab_id):
        self.active_tab_ids.append(tab_id)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_agent_over_chrome_bridge_delegates_to_bridge_page():
    from midscene.web_integration.bridge_mode.agent_cli_side import (
        AgentOverChromeBridge,
    )

    page = _FakeBridgePage()
    agent = AgentOverChromeBridge(
        AgentOptions(generate_report=False),
        page=page,
        close_new_tabs_after_disconnect=True,
        enable_water_flow_animation=False,
    )

    with patch(
        "midscene.web_integration.bridge_mode.agent_cli_side.asyncio.sleep",
        AsyncMock(),
    ):
        await agent.connect_new_tab_with_url(
            "https://example.com", {"activateTab": False}
        )
        await agent.connect_current_tab({"tabId": 2})

    assert page.new_tab_calls == [
        (
            "https://example.com",
            {"activateTab": False, "enableWaterFlowAnimation": False},
        )
    ]
    assert page.current_tab_calls == [
        {"tabId": 2, "enableWaterFlowAnimation": False}
    ]
    assert page.water_flow_calls == [False, False]
    assert page.destroy_options == [{"closeTab": True}, {"closeTab": True}]

    assert await agent.get_browser_tab_list() == [
        {"id": 1, "title": "tab", "url": "https://example.com"}
    ]
    await agent.set_active_tab_id("3")
    assert page.active_tab_ids == [3]

    tip_result = agent.options.on_task_start_tip("working")
    await tip_result
    assert page.status_messages == ["working"]

    await agent.destroy(True)
    assert page.destroy_options[-1] == {"closeTab": True}
    assert page.closed is True


def test_get_bridge_page_in_cli_side_resolves_host_and_port():
    from midscene.web_integration.bridge_mode import (
        BridgeWebPage,
        get_bridge_page_in_cli_side,
    )

    page = get_bridge_page_in_cli_side(allow_remote_access=True)
    assert isinstance(page, BridgeWebPage)
    assert page.host == "0.0.0.0"
    assert page.port == 3766

    explicit = get_bridge_page_in_cli_side(host="localhost", port=4000)
    assert explicit.host == "localhost"
    assert explicit.port == 4000


@pytest.mark.asyncio
async def test_bridge_web_page_connect_paths(monkeypatch):
    from midscene.web_integration.bridge_mode import page_browser_side

    calls = []

    class FakeServer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def listen(self, timeout=30.0):
            calls.append(("listen", timeout))

        async def call(self, method, args=None, timeout=30.0):
            calls.append((method, args))
            return None

    monkeypatch.setattr(page_browser_side, "BridgeServer", FakeServer)

    page = page_browser_side.BridgeWebPage(connect_options={"forceSameTabNavigation": True})
    await page.connect()
    assert calls[0][0] == "listen"
    assert calls[1] == (
        "connectCurrentTab",
        [{"forceSameTabNavigation": True}],
    )

    await page.connect_new_tab_with_url(
        "https://example.com", {"activateTab": False}
    )
    assert calls[-1] == (
        "connectNewTabWithUrl",
        [
            "https://example.com",
            {"forceSameTabNavigation": True, "activateTab": False},
        ],
    )

    await page.set_destroy_options({"closeTab": True})
    assert calls[-1] == ("setDestroyOptions", [{"closeTab": True}])


class _PageManager:
    def __init__(self, summaries):
        self.summaries = summaries
        self.selected = None

    async def page_summaries(self):
        return self.summaries

    async def page_summary_by_index(self, index):
        return self.summaries[index]

    async def set_active_page_by_selector(self, selector):
        self.selected = selector


@pytest.mark.asyncio
async def test_browser_page_actions_list_info_and_feedback():
    summaries = [
        {
            "index": index,
            "active": index == 2,
            "title": f"Page {index}",
            "url": f"https://example.com/{index}",
        }
        for index in range(10)
    ]
    manager = _PageManager(summaries)
    feedback = []
    actions = create_browser_agent_page_actions(lambda: manager, feedback.append)
    by_name = {action.name: action for action in actions}

    visible = await by_name["ListBrowserPages"].execute({"offset": 4}, None, None)
    assert [item["index"] for item in visible] == [4, 5, 6, 7, 8, 9]
    assert "ListBrowserPages 4-9 of 10" in feedback[0]
    assert "active 2" in feedback[0]

    with pytest.raises(ValueError, match="out of range"):
        await by_name["ListBrowserPages"].execute({"offset": 10}, None, None)

    info = await by_name["GetBrowserPageInfo"].execute({"index": 3}, None, None)
    assert info["url"] == "https://example.com/3"
    assert "GetBrowserPageInfo index 3" in feedback[-1]

    await by_name["SetActivePage"].execute({"index": 2}, None, None)
    assert manager.selected == {"index": 2}


def test_append_browser_agent_page_actions_dedupes_by_name():
    from types import SimpleNamespace

    custom = [SimpleNamespace(name="ListBrowserPages")]
    browser = [
        SimpleNamespace(name="ListBrowserPages"),
        SimpleNamespace(name="SetActivePage"),
    ]
    result = append_browser_agent_page_actions(custom, browser)
    assert result == [custom[0], browser[1]]
    assert append_browser_agent_page_actions(None, browser) == browser


def test_truncate_feedback_value_matches_upstream():
    assert _truncate_feedback_value("abcde", 5) == "abcde"
    assert _truncate_feedback_value("abcdefghij", 5) == "abc…j"
    assert _truncate_feedback_value("abc", 0) == ""
    assert _truncate_feedback_value("abc", 2) == "a…"
