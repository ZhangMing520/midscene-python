"""Web CDP agent tools (upstream web-integration/agent-tools-cdp.ts).

The upstream implementation connects through puppeteer-core.  The Python port
connects to the same Chrome DevTools Protocol endpoint through Playwright,
whose async page API is adapted to the small puppeteer-shaped surface used by
the tab tools.
"""

import asyncio
import inspect
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

from midscene.core.agent.agent_options import AgentOptions, coerce_agent_options
from midscene.core.agent.agent import Agent
from midscene.shared.agent_tools.agent_behavior_init_args import (
    extract_agent_behavior_init_args,
    get_agent_init_args_signature,
    should_rebuild_agent_for_init_args,
)
from midscene.shared.agent_tools.base_tools import BaseMidsceneTools, InitArgSpec
from midscene.shared.agent_tools.types import ToolDefinition, ToolResult
from midscene.web_integration.agent_init_args import (
    WEB_CDP_AGENT_INIT_ARG_SHAPE,
    adapt_web_cdp_agent_init_args,
)
from midscene.web_integration.agent_tools import _StaticWebPage
from midscene.web_integration.agent_tools_tabs import (
    create_tab_tools,
    get_target_id,
    is_page_closed,
    page_title,
    page_url,
)
from midscene.web_integration.cdp_target_store import (
    cleanup_target_id_file,
    read_saved_target_id,
    save_target_id,
)
from midscene.web_integration.common.browser_agent import WebAgentCore

debug = logger

# CDP target discovery may need a brief moment after the WebSocket opens.
CDP_TARGET_DISCOVERY_DELAY_MS = 500


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _http_get_json(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


async def _get_proxy_endpoint(chrome_endpoint: str) -> str:
    """Resolve a page-level CDP URL to its browser-level endpoint.

    The Node implementation also starts a local WebSocket proxy to avoid
    repeated Chrome permission popups.  Playwright connects to the browser
    endpoint directly, so only endpoint resolution is needed here.
    """
    if "/devtools/page/" not in chrome_endpoint:
        return chrome_endpoint

    parsed = urlparse(chrome_endpoint)
    if not parsed.netloc:
        raise RuntimeError(f"Invalid CDP endpoint URL: {chrome_endpoint}")
    try:
        info = await asyncio.to_thread(
            _http_get_json, f"http://{parsed.netloc}/json/version"
        )
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            "Cannot use page-level CDP endpoint directly. Playwright requires "
            "a browser-level endpoint (e.g., "
            "ws://host:port/devtools/browser/<id>). Auto-resolution via "
            f"/json/version failed: {error}."
        ) from error

    endpoint = info.get("webSocketDebuggerUrl")
    if not endpoint:
        raise RuntimeError(
            "webSocketDebuggerUrl not found in /json/version response"
        )
    return endpoint


class _PlaywrightCdpBrowser:
    """Playwright browser wrapped in the puppeteer-shaped browser surface."""

    def __init__(self, browser: Any, playwright: Any = None) -> None:
        self.browser = browser
        self._playwright = playwright
        self._target_ids: Dict[int, str] = {}

    def underlying_browser(self) -> Any:
        return self.browser

    async def pages(self) -> List[Any]:
        return [
            page
            for context in self.browser.contexts
            for page in context.pages
        ]

    async def new_page(self) -> Any:
        contexts = self.browser.contexts
        context = contexts[0] if contexts else await self.browser.new_context()
        return await context.new_page()

    async def target_id(self, page: Any) -> Optional[str]:
        direct = get_target_id(page)
        if direct:
            return direct
        cached = self._target_ids.get(id(page))
        if cached:
            return cached
        context = getattr(page, "context", None)
        if context is None:
            return None
        session = await context.new_cdp_session(page)
        try:
            info = await session.send("Target.getTargetInfo")
        finally:
            await session.detach()
        target = (info or {}).get("targetInfo", {}).get("targetId")
        if target:
            self._target_ids[id(page)] = target
        return target

    async def disconnect(self) -> None:
        try:
            await self.browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()


async def _connect_browser(endpoint: str) -> _PlaywrightCdpBrowser:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(endpoint)
    return _PlaywrightCdpBrowser(browser, playwright)


async def _page_bring_to_front(page: Any) -> None:
    bring = getattr(page, "bring_to_front", None) or getattr(
        page, "bringToFront", None
    )
    if bring is not None:
        await _maybe_await(bring())


async def _page_set_extra_http_headers(
    page: Any, headers: Dict[str, str]
) -> None:
    setter = getattr(page, "set_extra_http_headers", None) or getattr(
        page, "setExtraHTTPHeaders", None
    )
    if setter is not None:
        await _maybe_await(setter(headers))


async def _page_goto(page: Any, url: str) -> None:
    goto = getattr(page, "goto", None)
    if goto is None:
        raise RuntimeError("The selected CDP page cannot navigate to a URL")
    await _maybe_await(
        goto(url, timeout=30000, wait_until="domcontentloaded")
    )


async def _page_screenshot(page: Any) -> Optional[str]:
    screenshot = getattr(page, "screenshot_base64", None)
    if screenshot is None:
        return None
    value = screenshot()
    value = await _maybe_await(value)
    return value or None


class CdpBrowserAgent(WebAgentCore):
    """Core agent bound to a page selected over the CDP connection."""

    def __init__(
        self,
        interface: Any,
        active_page: Any,
        browser: Any = None,
        options: Optional[AgentOptions] = None,
        interface_factory: Any = None,
    ) -> None:
        super().__init__(interface, options)
        self._active_page = active_page
        self._browser = browser
        self._interface_factory = interface_factory
        self.set_active_page_calls: List[Any] = []

    @property
    def page(self) -> Any:
        return self.interface

    @property
    def active_page(self) -> Any:
        return self._active_page

    async def pages(self) -> List[Any]:
        if self._browser is None:
            pages = [self._active_page]
        else:
            pages = await _maybe_await(self._browser.pages())
        return [page for page in pages if not is_page_closed(page)]

    async def set_active_page(self, page: Any) -> None:
        if is_page_closed(page):
            raise ValueError("Cannot activate a closed CDP tab.")
        self._active_page = page
        self.set_active_page_calls.append(page)
        if self._interface_factory is not None:
            self.interface = self._interface_factory(page)
        await _page_bring_to_front(page)


class WebCdpMidsceneTools(BaseMidsceneTools):
    """Tools manager for Web CDP mode."""

    def __init__(self, cdp_endpoint: str) -> None:
        super().__init__()
        self.cdp_endpoint = cdp_endpoint
        self.init_arg_spec = InitArgSpec(
            namespace="web",
            shape=WEB_CDP_AGENT_INIT_ARG_SHAPE,
            cli={"preferBareKeys": True},
            adapt=adapt_web_cdp_agent_init_args,
        )
        self.active_browser: Any = None
        self.last_init_args_signature: Optional[str] = None

    def get_cli_report_session_name(self) -> str:
        return "midscene-web"

    def create_temporary_device(self) -> Any:
        return _StaticWebPage()

    def _create_page_interface(self, page: Any) -> Any:
        underlying_browser = (
            self.active_browser.underlying_browser()
            if hasattr(self.active_browser, "underlying_browser")
            else self.active_browser
        )
        context = getattr(page, "context", None)
        if context is None or not hasattr(page, "goto"):
            return page
        from midscene.web_integration.playwright.page import PlaywrightWebPage

        return PlaywrightWebPage(page, context, underlying_browser)

    async def _target_id_for(self, page: Any) -> Optional[str]:
        resolver = (
            getattr(self.active_browser, "target_id", None)
            if self.active_browser is not None
            else None
        )
        if callable(resolver):
            value = await _maybe_await(resolver(page))
            if value:
                return value
        return get_target_id(page)

    async def ensure_agent(self, init_param: Any = None) -> Agent:
        init_args = init_param or {}
        navigate_to_url = init_args.get("url")
        next_signature = get_agent_init_args_signature(init_args)
        should_navigate = isinstance(navigate_to_url, str)

        if self.agent is not None and (
            should_navigate
            or should_rebuild_agent_for_init_args(
                self.last_init_args_signature, next_signature
            )
        ):
            try:
                await self.agent.destroy()
            except Exception as error:  # noqa: BLE001
                debug.debug("Failed to destroy agent during re-init: %s", error)
            self.agent = None

        if self.agent is not None:
            return self.agent

        if self.active_browser is None:
            endpoint = await _get_proxy_endpoint(self.cdp_endpoint)
            self.active_browser = await _connect_browser(endpoint)

        pages = list(await _maybe_await(self.active_browser.pages()))
        if not pages:
            await asyncio.sleep(CDP_TARGET_DISCOVERY_DELAY_MS / 1000)
            pages = list(await _maybe_await(self.active_browser.pages()))

        web_pages = [
            page for page in pages if re.match(r"^https?://", page_url(page))
        ]

        if should_navigate:
            if web_pages:
                page = web_pages[-1]
                await _page_bring_to_front(page)
            else:
                page = await _maybe_await(self.active_browser.new_page())
        else:
            saved_target_id = read_saved_target_id()
            matched_page = None
            if saved_target_id and pages:
                for candidate in pages:
                    if await self._target_id_for(candidate) == saved_target_id:
                        matched_page = candidate
                        break
            if matched_page is not None:
                page = matched_page
            elif web_pages:
                page = web_pages[-1]
            elif pages:
                page = pages[-1]
            else:
                page = await _maybe_await(self.active_browser.new_page())
            await _page_bring_to_front(page)

        headers = init_args.get("extraHTTPHeaders")
        if headers:
            await _page_set_extra_http_headers(page, headers)

        if should_navigate:
            await _page_goto(page, navigate_to_url)

        target_id = await self._target_id_for(page)
        if target_id:
            save_target_id(target_id)

        report_options = self.read_cli_report_agent_options() or {}
        behavior = extract_agent_behavior_init_args(init_args) or {}
        options = coerce_agent_options({**behavior, **report_options})
        self.agent = CdpBrowserAgent(
            interface=self._create_page_interface(page),
            active_page=page,
            browser=self.active_browser,
            options=options,
            interface_factory=self._create_page_interface,
        )
        self.last_init_args_signature = next_signature
        return self.agent

    async def destroy(self) -> None:
        try:
            active_page = getattr(self.agent, "active_page", None)
            if active_page is not None and not is_page_closed(active_page):
                target_id = await self._target_id_for(active_page)
                if target_id:
                    save_target_id(target_id)
        finally:
            try:
                await super().destroy()
            finally:
                if self.active_browser is not None:
                    browser = self.active_browser
                    self.active_browser = None
                    await _maybe_await(browser.disconnect())

    async def _list_tabs(self) -> List[Dict[str, Any]]:
        agent = self.agent if self.agent is not None else await self.ensure_agent()
        active_page = getattr(agent, "active_page", None)
        tabs: List[Dict[str, Any]] = []
        for page in await agent.pages():
            tabs.append(
                {
                    "id": await self._target_id_for(page),
                    "title": await page_title(page),
                    "url": page_url(page),
                    "active": page is active_page,
                }
            )
        return tabs

    async def _select_tab(self, tab_id: str) -> None:
        agent = self.agent if self.agent is not None else await self.ensure_agent()
        pages = await agent.pages()
        page = None
        for candidate in pages:
            if await self._target_id_for(candidate) == tab_id:
                page = candidate
                break
        if page is None:
            raise ValueError(
                f"Tab {tab_id} does not exist or has closed. Run tabs again."
            )
        previous_page = agent.active_page
        await agent.set_active_page(page)
        try:
            save_target_id(tab_id)
        except Exception as error:
            try:
                await agent.set_active_page(previous_page)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Failed to save the selected tab and restore the previous "
                    f"page. ({rollback_error})"
                ) from error
            raise

    def prepare_platform_tools(self) -> List[ToolDefinition]:
        async def connect(args: Dict[str, Any]) -> ToolResult:
            init_args = self.extract_agent_init_param(args) or {}
            url = init_args.get("url")

            if self.agent is not None:
                try:
                    await self.agent.destroy()
                except Exception as error:  # noqa: BLE001
                    debug.debug(
                        "Failed to destroy agent during connect: %s", error
                    )
                self.agent = None
                self.last_init_args_signature = None

            report_session = self.create_new_cli_report_session(
                url or "current-page"
            )
            self.commit_cli_report_session(report_session)
            agent = await self.ensure_agent(init_args)

            page = getattr(agent, "active_page", None)
            screenshot = await _page_screenshot(page) if page else None
            content: List[Dict[str, Any]] = [
                {
                    "type": "text",
                    "text": f"Connected via CDP to: {url or 'current page'}",
                }
            ]
            if screenshot:
                content.extend(self.build_screenshot_content(screenshot))
            return ToolResult(content)

        async def disconnect(_args: Dict[str, Any]) -> ToolResult:
            if self.agent is not None:
                try:
                    await self.agent.destroy()
                except Exception as error:  # noqa: BLE001
                    debug.debug(
                        "Failed to destroy agent during disconnect: %s", error
                    )
                self.agent = None
                self.last_init_args_signature = None
            if self.active_browser is not None:
                browser = self.active_browser
                self.active_browser = None
                await _maybe_await(browser.disconnect())
            cleanup_target_id_file()
            return self.build_text_result(
                "Disconnected from web page (browser still running externally)"
            )

        return [
            *create_tab_tools(
                {"list": self._list_tabs, "select": self._select_tab}
            ),
            ToolDefinition(
                name="web_connect",
                description=(
                    "Connect to a web page via CDP. Opens a new tab with the "
                    "given URL, or reuses the current page."
                ),
                schema=self.get_agent_init_arg_schema(),
                cli=self.get_agent_init_arg_cli_metadata(),
                handler=connect,
            ),
            ToolDefinition(
                name="web_disconnect",
                description=(
                    "Disconnect from current web page. The browser stays "
                    "running (managed externally)."
                ),
                schema={},
                handler=disconnect,
            ),
        ]


__all__ = [
    "CDP_TARGET_DISCOVERY_DELAY_MS",
    "CdpBrowserAgent",
    "WebCdpMidsceneTools",
]
