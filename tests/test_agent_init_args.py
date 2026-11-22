"""Port of upstream packages/web-integration/tests/unit-test/agent-init-args.test.ts.

The upstream suite drives the Node-only web agent tools
(``WebMidsceneTools``/``WebCdpMidsceneTools``/``WebPuppeteerMidsceneTools``).
Those modules are exempt from the Python port, so tests that require them are
kept with the upstream case name and skipped; the remaining cases exercise the
ported init-arg shapes/adapters, config factory and bridge agent.
"""

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
from midscene.web_integration.bridge_mode.agent_cli_side import (
    AgentOverChromeBridge,
)

_PUPPETEER_REASON = "Puppeteer driver is not implemented in the Python SDK"
_WEB_AGENT_TOOLS_REASON = (
    "The web agent tools layer is not implemented in the Python SDK"
)
_CDP_TOOLS_REASON = "CDP agent tools are not implemented in the Python SDK"


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


@pytest.mark.skip(reason=_CDP_TOOLS_REASON)
def test_lists_and_switches_cdp_tabs_using_the_shared_browser_agent_and_target_store():
    pass


@pytest.mark.parametrize("failure_point", ["connect", "readback", "mismatch"])
@pytest.mark.skip(reason=_WEB_AGENT_TOOLS_REASON)
def test_cleans_up_a_new_bridge_agent_when_tab_reconnection_fails_at(
    failure_point,
):
    pass


@pytest.mark.skip(reason=_WEB_AGENT_TOOLS_REASON)
def test_reuses_the_selected_bridge_agent_with_unchanged_behavior_options():
    pass


@pytest.mark.skip(reason=_WEB_AGENT_TOOLS_REASON)
def test_reports_bridge_cleanup_failure_and_does_not_reuse_the_disposed_agent():
    pass


@pytest.mark.skip(reason=_WEB_AGENT_TOOLS_REASON)
def test_switches_bridge_tabs_by_reconnecting_to_an_existing_id_without_navigating():
    pass


@pytest.mark.parametrize(
    "mode",
    [
        "bridge",
        pytest.param(
            "puppeteer", marks=pytest.mark.skip(reason=_PUPPETEER_REASON)
        ),
        "cdp",
    ],
)
def test_exposes_common_web_init_args_in_mode(mode):
    shape = (
        WEB_CDP_AGENT_INIT_ARG_SHAPE
        if mode == "cdp"
        else WEB_AGENT_INIT_ARG_SHAPE
    )
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
        pytest.param(
            "bridge",
            marks=pytest.mark.skip(reason=_WEB_AGENT_TOOLS_REASON),
        ),
        pytest.param(
            "puppeteer",
            marks=pytest.mark.skip(reason=_PUPPETEER_REASON),
        ),
        pytest.param(
            "cdp",
            marks=pytest.mark.skip(reason=_CDP_TOOLS_REASON),
        ),
    ],
)
def test_reopens_or_renavigates_when_the_same_web_url_is_passed_twice_in_mode(
    mode,
):
    pass


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
    bridge_schema = create_namespaced_init_arg_schema(
        "web", WEB_AGENT_INIT_ARG_SHAPE
    )
    cdp_schema = create_namespaced_init_arg_schema(
        "web", WEB_CDP_AGENT_INIT_ARG_SHAPE
    )

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
