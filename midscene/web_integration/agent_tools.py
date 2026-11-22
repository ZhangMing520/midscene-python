"""Web bridge agent tools (upstream web-integration/agent-tools.ts)."""

import inspect
import re
from typing import Any, Dict, List, Optional

from midscene.core.agent.agent_options import AgentOptions, coerce_agent_options
from midscene.core.types import InterfaceType
from midscene.shared.agent_tools.agent_behavior_init_args import (
    extract_agent_behavior_init_args,
    get_agent_init_args_signature,
    should_rebuild_agent_for_init_args,
)
from midscene.shared.agent_tools.base_tools import BaseMidsceneTools, InitArgSpec
from midscene.shared.agent_tools.types import ToolDefinition, ToolResult
from midscene.web_integration.agent_init_args import (
    WEB_AGENT_INIT_ARG_SHAPE,
    adapt_web_agent_init_args,
)
from midscene.web_integration.agent_tools_tabs import create_tab_tools
from midscene.web_integration.bridge_mode.agent_cli_side import (
    AgentOverChromeBridge,
)

_MAX_SAFE_INTEGER = 2**53 - 1
_INVALID_TAB_ID = re.compile(r"^[1-9]\d*$")
_NOT_SWITCHED_ERROR = (
    "The browser extension did not switch tabs. Update the Midscene "
    "extension and retry."
)


class _StaticWebPage:
    """Temporary device used to read the action space before connecting."""

    interface_type = InterfaceType.WEB


def _tab_field(tab: Any, key: str) -> Any:
    if isinstance(tab, dict):
        return tab.get(key)
    return getattr(tab, key, None)


def build_bridge_agent_options(
    init_args: Optional[Dict[str, Any]],
    report_options: Optional[Dict[str, Any]] = None,
) -> AgentOptions:
    """Merge behavior init args and report options into AgentOptions."""
    behavior = extract_agent_behavior_init_args(init_args) or {}
    return coerce_agent_options({**behavior, **(report_options or {})})


class WebMidsceneTools(BaseMidsceneTools):
    """Tools manager for Web bridge mode."""

    def __init__(self) -> None:
        super().__init__()
        self.init_arg_spec = InitArgSpec(
            namespace="web",
            shape=WEB_AGENT_INIT_ARG_SHAPE,
            cli={"preferBareKeys": True},
            adapt=adapt_web_agent_init_args,
        )
        self.last_init_args_signature: Optional[str] = None
        self.last_init_args: Optional[Dict[str, Any]] = None

    def get_cli_report_session_name(self) -> str:
        return "midscene-web"

    def create_temporary_device(self) -> Any:
        return _StaticWebPage()

    async def ensure_agent(
        self, init_param: Any = None
    ) -> AgentOverChromeBridge:
        init_args = init_param or {}
        next_signature = get_agent_init_args_signature(init_args)
        should_open_url = isinstance(init_args.get("url"), str)

        if (
            self.agent is not None
            and not should_open_url
            and not should_rebuild_agent_for_init_args(
                self.last_init_args_signature, next_signature
            )
        ):
            return self.agent

        return await self._reconnect_agent(init_args)

    async def destroy(self) -> None:
        agent = self.agent
        self.agent = None
        self.last_init_args = None
        self.last_init_args_signature = None
        if agent is not None:
            await agent.destroy()

    async def _reconnect_agent(
        self,
        init_args: Optional[Dict[str, Any]] = None,
        tab_id: Optional[int] = None,
    ) -> AgentOverChromeBridge:
        await self.destroy()
        agent = await self._init_bridge_mode_agent(init_args, tab_id)
        self.agent = agent
        self.last_init_args = init_args
        self.last_init_args_signature = get_agent_init_args_signature(init_args)
        return agent

    async def _init_bridge_mode_agent(
        self,
        init_args: Optional[Dict[str, Any]] = None,
        tab_id: Optional[int] = None,
    ) -> AgentOverChromeBridge:
        url = (init_args or {}).get("url")
        options = build_bridge_agent_options(
            init_args, self.read_cli_report_agent_options()
        )
        agent = AgentOverChromeBridge(options, close_conflict_server=True)

        try:
            if not url:
                await agent.connect_current_tab(
                    {"tabId": tab_id, "forceSameTabNavigation": False}
                )
            else:
                await agent.connect_new_tab_with_url(
                    url, {"forceSameTabNavigation": False}
                )
            if tab_id is not None:
                active_tab_id = await agent.page.get_active_tab_id()
                if active_tab_id is None or int(active_tab_id) != tab_id:
                    raise RuntimeError(_NOT_SWITCHED_ERROR)
            return agent
        except Exception as error:
            try:
                await agent.destroy()
            except Exception as cleanup_error:
                raise RuntimeError(
                    "Failed to connect and clean up the Bridge agent. "
                    f"({cleanup_error})"
                ) from error
            raise

    async def _list_tabs(self) -> List[Dict[str, Any]]:
        agent = self.agent if self.agent is not None else await self.ensure_agent()
        active_id = str(await agent.page.get_active_tab_id())
        tabs = await agent.get_browser_tab_list()
        return [
            {
                "id": str(_tab_field(tab, "id")),
                "title": _tab_field(tab, "title"),
                "url": _tab_field(tab, "url"),
                "active": str(_tab_field(tab, "id")) == active_id,
            }
            for tab in tabs
        ]

    async def _select_tab(self, tab_id: str) -> None:
        if not isinstance(tab_id, str) or not _INVALID_TAB_ID.match(tab_id):
            raise ValueError(f"Invalid Bridge tab ID: {tab_id}")
        if int(tab_id) > _MAX_SAFE_INTEGER:
            raise ValueError(f"Invalid Bridge tab ID: {tab_id}")

        agent = self.agent if self.agent is not None else await self.ensure_agent()
        tabs = await agent.get_browser_tab_list()
        if not any(str(_tab_field(tab, "id")) == tab_id for tab in tabs):
            raise ValueError(
                f"Tab {tab_id} does not exist or has closed. Run tabs again."
            )
        await self._reconnect_agent(
            {
                key: value
                for key, value in (self.last_init_args or {}).items()
                if key != "url"
            },
            int(tab_id),
        )

    def prepare_platform_tools(self) -> List[ToolDefinition]:
        async def connect(args: Dict[str, Any]) -> ToolResult:
            init_args = self.extract_agent_init_param(args) or {}
            url = init_args.get("url")

            report_session = self.create_new_cli_report_session(
                url or "current-tab"
            )
            self.commit_cli_report_session(report_session)
            agent = await self._reconnect_agent(init_args)

            content: List[Dict[str, Any]] = [
                {"type": "text", "text": f"Connected to: {url or 'current tab'}"}
            ]
            page = getattr(agent, "page", None)
            screenshot_fn = getattr(page, "screenshot_base64", None)
            if screenshot_fn is not None:
                screenshot = screenshot_fn()
                if inspect.isawaitable(screenshot):
                    screenshot = await screenshot
                if screenshot:
                    content.extend(self.build_screenshot_content(screenshot))
            return ToolResult(content)

        async def disconnect(_args: Dict[str, Any]) -> ToolResult:
            if self.agent is None:
                return self.build_text_result(
                    "No active connection to disconnect"
                )
            await self.destroy()
            return self.build_text_result("Disconnected from web page")

        return [
            *create_tab_tools(
                {"list": self._list_tabs, "select": self._select_tab}
            ),
            ToolDefinition(
                name="web_connect",
                description=(
                    "Connect to web page. If URL provided, opens new tab; "
                    "otherwise connects to current tab."
                ),
                schema=self.get_agent_init_arg_schema(),
                cli=self.get_agent_init_arg_cli_metadata(),
                handler=connect,
            ),
            ToolDefinition(
                name="web_disconnect",
                description=(
                    "Disconnect from current web page and release browser "
                    "resources"
                ),
                schema={},
                handler=disconnect,
            ),
        ]


__all__ = ["WebMidsceneTools", "build_bridge_agent_options"]
