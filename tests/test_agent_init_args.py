"""Port of upstream packages/web-integration/tests/unit-test/agent-init-args.test.ts.

The bridge and CDP tool suites are ported with fake agents/browsers; the
Puppeteer driver itself is not implemented in the Python SDK, so the
Puppeteer-only cases keep the upstream case name and are skipped.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from midscene.cli.config_factory import _build_agent_options
from midscene.core.types import InterfaceType
from midscene.shared.agent_tools.base_tools import BaseMidsceneTools, InitArgSpec
from midscene.shared.agent_tools.init_arg_utils import (
    create_namespaced_init_arg_schema,
)
from midscene.web_integration.agent_init_args import (
    WEB_AGENT_INIT_ARG_SHAPE,
    WEB_CDP_AGENT_INIT_ARG_SHAPE,
    adapt_web_agent_init_args,
    adapt_web_cdp_agent_init_args,
    get_agent_init_args,
)
from midscene.web_integration.agent_tools import WebMidsceneTools
from midscene.web_integration.agent_tools_cdp import WebCdpMidsceneTools
from midscene.web_integration.bridge_mode.agent_cli_side import (
    AgentOverChromeBridge,
)

_PUPPETEER_REASON = "Puppeteer driver is not implemented in the Python SDK"
_VALID_PNG_BASE64 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _FakeBridgePage:
    interface_type = InterfaceType.WEB

    def __init__(self):
        self.status_messages = []
        self.new_tab_calls = []
        self.current_tab_calls = []
        self.water_flow_calls = []
        self.destroy_options = []

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

    async def set_active_tab_id(self, tab_id):
        pass

    async def close(self):
        pass


class _CdpTools(BaseMidsceneTools):
    init_arg_spec = InitArgSpec(
        namespace="web",
        shape=WEB_CDP_AGENT_INIT_ARG_SHAPE,
        cli={"preferBareKeys": True},
    )

    async def ensure_agent(self, init_param=None):
        return None

    def create_temporary_device(self):
        return None


class _FakeBridgeAgentPage:
    def __init__(self, active_tab_id=42):
        self.active_tab_id = active_tab_id
        self.screenshot_calls = 0

    async def get_active_tab_id(self):
        if isinstance(self.active_tab_id, BaseException):
            raise self.active_tab_id
        return self.active_tab_id

    async def screenshot_base64(self):
        self.screenshot_calls += 1
        return _VALID_PNG_BASE64


class _FakeBridgeAgent:
    def __init__(
        self,
        active_tab_id=42,
        tabs=None,
        fail_connect=False,
        destroy_error=None,
    ):
        self.page = _FakeBridgeAgentPage(active_tab_id)
        self.tabs = tabs or [
            {"id": "42", "title": "Example", "url": "https://example.com/"}
        ]
        self.connect_current_calls = []
        self.connect_new_tab_calls = []
        self.destroy_calls = 0
        self.fail_connect = fail_connect
        self.destroy_error = destroy_error

    async def get_browser_tab_list(self):
        return self.tabs

    async def connect_current_tab(self, options=None):
        self.connect_current_calls.append(options)
        if self.fail_connect:
            raise RuntimeError("bridge failure")

    async def connect_new_tab_with_url(self, url, options=None):
        self.connect_new_tab_calls.append((url, options))

    async def destroy(self):
        self.destroy_calls += 1
        if self.destroy_error is not None:
            error, self.destroy_error = self.destroy_error, None
            raise error


class _FakeCdpPage:
    interface_type = InterfaceType.WEB

    def __init__(self, url="https://example.com/", target_id="target-1"):
        self.url = url
        self.target_id = target_id
        self.goto_calls = []
        self.bring_to_front_calls = 0
        self.header_calls = []
        self.closed = False

    async def title(self):
        return "Example"

    def is_closed(self):
        return self.closed

    async def bring_to_front(self):
        self.bring_to_front_calls += 1

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))

    async def set_extra_http_headers(self, headers):
        self.header_calls.append(headers)

    def target(self):
        return {"_targetId": self.target_id}

    async def screenshot_base64(self):
        return _VALID_PNG_BASE64


class _FakeCdpBrowser:
    def __init__(self, pages):
        self._pages = pages
        self.new_page_calls = 0
        self.disconnect_calls = 0

    async def pages(self):
        return list(self._pages)

    async def new_page(self):
        self.new_page_calls += 1
        return self._pages[0]

    async def disconnect(self):
        self.disconnect_calls += 1


def _find_tool(tools, name):
    return next(tool for tool in tools.get_tool_definitions() if tool.name == name)


@pytest.mark.asyncio
async def test_lists_and_switches_cdp_tabs_using_the_shared_browser_agent_and_target_store():
    page = _FakeCdpPage()
    browser = _FakeCdpBrowser([page])
    tools = WebCdpMidsceneTools("ws://127.0.0.1:9222/devtools/1")
    await tools.init_tools()

    with (
        patch(
            "midscene.web_integration.agent_tools_cdp._connect_browser",
            AsyncMock(return_value=browser),
        ),
        patch(
            "midscene.web_integration.agent_tools_cdp.read_saved_target_id",
            return_value=None,
        ),
        patch("midscene.web_integration.agent_tools_cdp.save_target_id") as save_target,
    ):
        result = await _find_tool(tools, "web_tabs").handler({})
        assert json.loads(result.content[0]["text"]) == [
            {
                "id": "target-1",
                "title": "Example",
                "url": "https://example.com/",
                "active": True,
            }
        ]

        await _find_tool(tools, "web_switch-tab").handler({"id": "target-1"})
        save_target.assert_called_with("target-1")
        assert tools.agent.set_active_page_calls == [page]

        with pytest.raises(ValueError, match="does not exist or has closed"):
            await _find_tool(tools, "web_switch-tab").handler({"id": "missing"})

        await tools.destroy()


@pytest.mark.parametrize("failure_point", ["connect", "readback", "mismatch"])
@pytest.mark.asyncio
async def test_cleans_up_a_new_bridge_agent_when_tab_reconnection_fails_at(
    failure_point,
):
    replacement = _FakeBridgeAgent(active_tab_id=99)
    if failure_point == "connect":
        replacement.fail_connect = True
    elif failure_point == "readback":
        replacement.page.active_tab_id = RuntimeError("bridge failure")

    tools = WebMidsceneTools()
    await tools.init_tools()
    first = _FakeBridgeAgent()

    with patch(
        "midscene.web_integration.agent_tools.AgentOverChromeBridge",
        side_effect=[first, replacement],
    ):
        await _find_tool(tools, "web_tabs").handler({})
        expected = (
            "did not switch tabs" if failure_point == "mismatch" else "bridge failure"
        )
        with pytest.raises(RuntimeError, match=expected):
            await _find_tool(tools, "web_switch-tab").handler({"id": "42"})
        assert replacement.destroy_calls == 1
        await tools.destroy()


@pytest.mark.asyncio
async def test_reuses_the_selected_bridge_agent_with_unchanged_behavior_options():
    tools = WebMidsceneTools()
    await tools.init_tools()
    first = _FakeBridgeAgent()
    second = _FakeBridgeAgent()

    with patch(
        "midscene.web_integration.agent_tools.AgentOverChromeBridge",
        side_effect=[first, second],
    ) as factory:
        args = {"web": {"waitAfterAction": 650}}
        try:
            await _find_tool(tools, "take_screenshot").handler(args)
            await _find_tool(tools, "web_switch-tab").handler({"id": "42"})
            await _find_tool(tools, "take_screenshot").handler(args)
            assert factory.call_count == 2
            assert factory.call_args.args[0].wait_after_action_ms == 650
        finally:
            await tools.destroy()


@pytest.mark.asyncio
async def test_reports_bridge_cleanup_failure_and_does_not_reuse_the_disposed_agent():
    tools = WebMidsceneTools()
    await tools.init_tools()
    first = _FakeBridgeAgent(destroy_error=RuntimeError("cleanup failed"))
    second = _FakeBridgeAgent()

    with patch(
        "midscene.web_integration.agent_tools.AgentOverChromeBridge",
        side_effect=[first, second],
    ) as factory:
        await _find_tool(tools, "web_tabs").handler({})
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await _find_tool(tools, "web_disconnect").handler({})

        await _find_tool(tools, "web_tabs").handler({})
        assert factory.call_count == 2
        assert first.destroy_calls == 1

        await tools.destroy()
        await tools.destroy()
        assert second.destroy_calls == 1


@pytest.mark.asyncio
async def test_switches_bridge_tabs_by_reconnecting_to_an_existing_id_without_navigating():
    tools = WebMidsceneTools()
    await tools.init_tools()
    first = _FakeBridgeAgent()
    second = _FakeBridgeAgent()

    with patch(
        "midscene.web_integration.agent_tools.AgentOverChromeBridge",
        side_effect=[first, second],
    ):
        with pytest.raises(ValueError, match="Invalid Bridge tab ID"):
            await _find_tool(tools, "web_switch-tab").handler({"id": "42oops"})
        with pytest.raises(ValueError, match="does not exist or has closed"):
            await _find_tool(tools, "web_switch-tab").handler({"id": "99"})

        await _find_tool(tools, "web_switch-tab").handler({"id": "42"})
        assert first.destroy_calls == 1
        assert second.connect_current_calls == [
            {"tabId": 42, "forceSameTabNavigation": False}
        ]
        assert second.connect_new_tab_calls == []
        await tools.destroy()


@pytest.mark.parametrize(
    "mode",
    [
        "bridge",
        pytest.param("puppeteer", marks=pytest.mark.skip(reason=_PUPPETEER_REASON)),
        "cdp",
    ],
)
def test_exposes_common_web_init_args_in_mode(mode):
    shape = WEB_CDP_AGENT_INIT_ARG_SHAPE if mode == "cdp" else WEB_AGENT_INIT_ARG_SHAPE
    take_screenshot_schema = create_namespaced_init_arg_schema("web", shape)
    connect_schema = create_namespaced_init_arg_schema("web", shape)

    for schema in (take_screenshot_schema, connect_schema):
        assert "web.url" in schema
        assert "web.waitAfterAction" in schema
    for schema in (take_screenshot_schema, connect_schema):
        assert "web.replanningCycleLimit" in schema
        assert "web.screenshotShrinkFactor" in schema


@pytest.mark.asyncio
async def test_passes_common_behavior_args_to_bridge_agent_creation():
    options = _build_agent_options(
        {
            "agent": {
                "waitAfterAction": 650,
                "replanningCycleLimit": 12,
                "aiActContext": "accept permission dialogs",
                "screenshotShrinkFactor": 2,
            }
        }
    )
    page = _FakeBridgePage()
    with patch(
        "midscene.web_integration.bridge_mode.agent_cli_side."
        "get_bridge_page_in_cli_side",
        return_value=page,
    ) as factory:
        agent = AgentOverChromeBridge(
            options,
            close_conflict_server=True,
            enable_water_flow_animation=False,
        )

    assert factory.call_args.kwargs["close_conflict_server"] is True
    assert options.wait_after_action_ms == 650
    assert options.replanning_cycle_limit == 12
    assert options.ai_act_context == "accept permission dialogs"
    assert options.screenshot_shrink_factor == 2

    with patch(
        "midscene.web_integration.bridge_mode.agent_cli_side.asyncio.sleep",
        AsyncMock(),
    ):
        await agent.connect_new_tab_with_url(
            "https://example.com", {"forceSameTabNavigation": False}
        )

    url, call_options = page.new_tab_calls[0]
    assert url == "https://example.com"
    assert call_options["forceSameTabNavigation"] is False


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_passes_common_behavior_args_to_puppeteer_agent_creation():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_reuses_the_saved_puppeteer_target_when_browser_pages_returns_newer_tabs_first():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_fails_instead_of_guessing_a_puppeteer_tab_when_the_saved_target_cannot_be_read():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_fails_the_current_command_when_the_puppeteer_target_cannot_be_saved():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_rejects_an_empty_puppeteer_target_file_as_corrupt_state():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_uses_the_existing_page_when_no_puppeteer_target_has_been_saved_yet():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_fails_when_puppeteer_does_not_expose_a_target_id_for_the_selected_page():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_persists_the_connected_puppeteer_target_and_clears_it_on_disconnect_and_close():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_reuses_the_puppeteer_agent_for_identical_init_args_and_rebuilds_when_they_change():
    pass


@pytest.mark.skip(reason=_PUPPETEER_REASON)
def test_rebuilds_the_puppeteer_agent_without_behavior_args_when_they_are_omitted_after_being_set():
    pass


@pytest.mark.parametrize(
    "mode",
    [
        "bridge",
        pytest.param(
            "puppeteer",
            marks=pytest.mark.skip(reason=_PUPPETEER_REASON),
        ),
        "cdp",
    ],
)
@pytest.mark.asyncio
async def test_reopens_or_renavigates_when_the_same_web_url_is_passed_twice_in_mode(
    mode,
):
    args = {"web": {"url": "https://example.com"}}

    if mode == "bridge":
        tools = WebMidsceneTools()
        await tools.init_tools()
        first = _FakeBridgeAgent()
        second = _FakeBridgeAgent()
        with patch(
            "midscene.web_integration.agent_tools.AgentOverChromeBridge",
            side_effect=[first, second],
        ) as factory:
            await _find_tool(tools, "take_screenshot").handler(args)
            await _find_tool(tools, "take_screenshot").handler(args)
            assert factory.call_count == 2
            assert (
                len(first.connect_new_tab_calls) + len(second.connect_new_tab_calls)
                == 2
            )
        await tools.destroy()
        return

    page = _FakeCdpPage()
    browser = _FakeCdpBrowser([page])
    tools = WebCdpMidsceneTools("ws://127.0.0.1:9222/devtools/1")
    await tools.init_tools()
    with (
        patch(
            "midscene.web_integration.agent_tools_cdp._connect_browser",
            AsyncMock(return_value=browser),
        ),
        patch(
            "midscene.web_integration.agent_tools_cdp.read_saved_target_id",
            return_value=None,
        ),
        patch("midscene.web_integration.agent_tools_cdp.save_target_id"),
    ):
        await _find_tool(tools, "take_screenshot").handler(args)
        await _find_tool(tools, "take_screenshot").handler(args)
        assert len(page.goto_calls) == 2
    await tools.destroy()


def test_passes_common_behavior_args_to_cdp_agent_creation():
    args = adapt_web_cdp_agent_init_args(
        {
            "waitAfterAction": 650,
            "replanningCycleLimit": 12,
            "aiActContext": "accept permission dialogs",
            "screenshotShrinkFactor": 2,
        }
    )

    assert args["waitAfterAction"] == 650
    assert args["replanningCycleLimit"] == 12
    assert args["aiActContext"] == "accept permission dialogs"
    assert args["screenshotShrinkFactor"] == 2


def test_exposes_extra_http_headers_only_in_cdp_mode():
    bridge_schema = create_namespaced_init_arg_schema("web", WEB_AGENT_INIT_ARG_SHAPE)
    cdp_schema = create_namespaced_init_arg_schema("web", WEB_CDP_AGENT_INIT_ARG_SHAPE)

    assert "web.extraHttpHeader" not in bridge_schema
    assert "web.extraHttpHeader" in cdp_schema
    metadata = _CdpTools().get_agent_init_arg_cli_metadata()
    assert (
        metadata["options"]["web.extraHttpHeader"]["preferredName"]
        == "extra-http-header"
    )


def test_combines_repeated_cdp_extra_http_headers_before_navigating():
    args = adapt_web_cdp_agent_init_args(
        {
            "url": "https://example.com",
            "extraHttpHeader": [
                "x-use-ppe:1",
                "x-tt-env:ppe_example",
                "x-callback-url:https://example.com/callback",
            ],
        }
    )

    assert args["extraHTTPHeaders"] == {
        "x-use-ppe": "1",
        "x-tt-env": "ppe_example",
        "x-callback-url": "https://example.com/callback",
    }


def test_does_not_apply_cdp_extra_http_headers_when_omitted():
    args = adapt_web_cdp_agent_init_args({"url": "https://example.com"})

    assert "extraHTTPHeaders" not in args


def test_accepts_one_cdp_extra_http_header_without_an_array():
    args = adapt_web_cdp_agent_init_args(
        {"url": "https://example.com", "extraHttpHeader": "x-use-ppe:1"}
    )

    assert args["extraHTTPHeaders"] == {"x-use-ppe": "1"}


@pytest.mark.parametrize(
    "entry", ["missing-colon", ":missing-name", "invalid name:value"]
)
def test_rejects_invalid_cdp_extra_http_header_entry(entry):
    with pytest.raises(ValueError, match="Name:Value"):
        adapt_web_cdp_agent_init_args({"extraHttpHeader": entry})


def test_rejects_an_empty_cdp_extra_http_header_array():
    with pytest.raises(ValueError, match="Name:Value"):
        adapt_web_cdp_agent_init_args({"extraHttpHeader": []})


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
