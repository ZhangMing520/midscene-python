"""Browser agent wrapper and page manager (upstream common/browser-agent.ts).

``WebAgentCore`` is the thin web-specific ``Agent`` subclass: it only adds the
browser-navigation retry predicate.  ``BrowserPageManager`` owns tab bookkeeping
(list/summaries/active page/new-page waiting) and is driven through an adapter,
so Playwright and the Chrome-extension bridge can share it without duplicating
the core agent.
"""

import asyncio
import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    TypedDict,
    TypeVar,
    Union,
)

from loguru import logger

from midscene.core.agent.agent import Agent
from midscene.core.agent.agent_options import AgentOptions
from midscene.web_integration.common.browser_agent_utils import (
    is_retryable_browser_navigation_error,
)

DEFAULT_NEW_PAGE_TIMEOUT = 5000

BrowserAgentPageScope = str

PageT = TypeVar("PageT")
NewPageEventT = TypeVar("NewPageEventT")


class BrowserAgentAdapter(Protocol[PageT, NewPageEventT]):
    """Driver-specific hooks consumed by :class:`BrowserPageManager`."""

    def pages(self) -> Union[List[PageT], Awaitable[List[PageT]]]:
        ...

    def new_page(self) -> Awaitable[PageT]:
        ...

    def is_page_closed(self, page: PageT) -> bool:
        ...

    def is_page_allowed(self, page: PageT) -> bool:
        ...

    def bring_to_front(self, page: PageT) -> Union[None, Awaitable[None]]:
        ...

    def page_title(self, page: PageT) -> Union[str, Awaitable[str]]:
        ...

    def page_url(self, page: PageT) -> str:
        ...

    def on_new_page(self, handler: Callable[[NewPageEventT], Any]) -> None:
        ...

    def off_new_page(self, handler: Callable[[NewPageEventT], Any]) -> None:
        ...

    def resolve_new_page(
        self, event: NewPageEventT
    ) -> Union[Optional[PageT], Awaitable[Optional[PageT]]]:
        ...

    def is_new_page_event(self, event: NewPageEventT) -> bool:
        ...


@dataclass
class BrowserAgentRuntimeOptions:
    """Runtime options for a browser agent (upstream type of the same name)."""

    agent_name: str
    page_scope: str
    force_same_tab_navigation: Optional[bool] = None
    auto_follow_new_page: Optional[bool] = None
    new_page_timeout: int = DEFAULT_NEW_PAGE_TIMEOUT


@dataclass
class ResolvedBrowserAgentRuntimeOptions:
    """Normalized runtime options for a browser agent."""

    page_scope: str
    force_same_tab_navigation: bool
    auto_follow_new_page: bool
    new_page_timeout: int


class BrowserAgentPageSummary(TypedDict):
    """``{index, active, title, url}`` summary of one browser page."""

    index: int
    active: bool
    title: str
    url: str


class BrowserAgentPageSelector(TypedDict, total=False):
    """``{index?, title?, url?}`` selector accepted by SetActivePage."""

    index: int
    title: str
    url: str


def resolve_browser_agent_runtime_options(
    options: Union[BrowserAgentRuntimeOptions, Dict[str, Any]],
) -> ResolvedBrowserAgentRuntimeOptions:
    """Validate page/browser scope options (upstream
    resolveBrowserAgentRuntimeOptions)."""
    if isinstance(options, dict):
        options = BrowserAgentRuntimeOptions(**options)

    if options.page_scope == "page":
        if options.auto_follow_new_page:
            raise ValueError(
                "[midscene] autoFollowNewPage requires browser mode for "
                f"{options.agent_name}. Use BrowserAgent when one agent should "
                "follow newly opened pages."
            )
        return ResolvedBrowserAgentRuntimeOptions(
            page_scope=options.page_scope,
            force_same_tab_navigation=(
                True
                if options.force_same_tab_navigation is None
                else options.force_same_tab_navigation
            ),
            auto_follow_new_page=False,
            new_page_timeout=options.new_page_timeout,
        )

    if options.force_same_tab_navigation is not None:
        raise ValueError(
            "[midscene] forceSameTabNavigation cannot be used in browser mode "
            f"for {options.agent_name}. Use PageAgent when same-tab navigation "
            "is required."
        )

    return ResolvedBrowserAgentRuntimeOptions(
        page_scope=options.page_scope,
        force_same_tab_navigation=False,
        auto_follow_new_page=bool(options.auto_follow_new_page),
        new_page_timeout=options.new_page_timeout,
    )


class WebAgentCore(Agent):
    """Core agent specialization shared by web page drivers."""

    def is_retryable_context_error(self, error: BaseException) -> bool:
        return is_retryable_browser_navigation_error(error)


class BrowserAgent(WebAgentCore):
    """Thin browser agent: a core agent bound to one web page.

    The heavy lifting (planning, locate, actions) stays in
    :class:`midscene.core.agent.agent.Agent`; this class only exposes the bound
    page and can optionally attach a :class:`BrowserPageManager`.
    """

    def __init__(
        self,
        interface: Any,
        options: Optional[AgentOptions] = None,
        page_manager: Optional["BrowserPageManager[Any, Any]"] = None,
    ):
        super().__init__(interface, options)
        self.page_manager = page_manager

    @property
    def page(self) -> Any:
        return self.interface


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _schedule(value: Any) -> None:
    if inspect.isawaitable(value):
        try:
            asyncio.ensure_future(value)
        except RuntimeError:
            # No running loop: dropping a listener removal is harmless.
            pass


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    trimmed = (value or "").strip()
    return trimmed.lower() if trimmed else None


def _page_summary_matches(
    summary: Dict[str, Any], title: Optional[str], url: Optional[str]
) -> bool:
    return (not title or title in str(summary["title"]).lower()) and (
        not url or url in str(summary["url"]).lower()
    )


def _describe_selector(selector: Dict[str, Any]) -> str:
    parts: List[str] = []
    if selector.get("index") is not None:
        parts.append(f"index {selector['index']}")
    title = (selector.get("title") or "").strip()
    if title:
        parts.append(f'title "{title}"')
    url = (selector.get("url") or "").strip()
    if url:
        parts.append(f'url "{url}"')
    return ", ".join(parts)


class BrowserPageManager:
    """Track and switch browser pages behind an agent adapter."""

    def __init__(
        self,
        agent_name: str,
        adapter: BrowserAgentAdapter,
        get_active_page: Callable[[], Any],
        set_active_page: Callable[[Any], None],
        auto_follow_new_page: bool = False,
        new_page_timeout: int = DEFAULT_NEW_PAGE_TIMEOUT,
        debug: Optional[Callable[[str], Any]] = None,
    ):
        self.agent_name = agent_name
        self.adapter = adapter
        self._get_active_page = get_active_page
        self._set_active_page = set_active_page
        self.new_page_timeout = new_page_timeout
        self.debug = debug or logger.debug

        self._new_page_handler = self._on_new_page_event
        if auto_follow_new_page:
            self.adapter.on_new_page(self._new_page_handler)

    @property
    def active_page(self) -> Any:
        return self._get_active_page()

    def pages(self) -> Any:
        return self.adapter.pages()

    async def page_summaries(self) -> List[Dict[str, Any]]:
        pages = await self.open_pages()
        active_page = self.active_page
        summaries: List[Dict[str, Any]] = []
        for page, active in zip(
            pages, [page is active_page for page in pages]
        ):
            summary = await self._try_page_summary(page, 0, active)
            if summary is not None:
                summaries.append(summary)
        return [
            {**summary, "index": index}
            for index, summary in enumerate(summaries)
        ]

    async def page_summary_by_index(self, index: int) -> Dict[str, Any]:
        pages = await self.open_pages()
        page = pages[index] if 0 <= index < len(pages) else None
        if page is None or self.adapter.is_page_closed(page):
            raise ValueError(
                f"[midscene] Cannot find {self.agent_name} page with index "
                f"{index}. Available page indexes: "
                f"{', '.join(str(i) for i in range(len(pages)))}"
            )

        summary = await self._try_page_summary(
            page, index, page is self.active_page
        )
        if summary is None:
            raise RuntimeError(
                f"[midscene] {self.agent_name} page at index {index} closed "
                "while reading its metadata. Run ListBrowserPages again."
            )
        return summary

    async def new_page(self) -> Any:
        page = await _maybe_await(self.adapter.new_page())
        await self.set_active_page(page)
        return page

    async def set_active_page(self, page: Any) -> None:
        if page is None or self.adapter.is_page_closed(page):
            raise ValueError(
                f"[midscene] Cannot set {self.agent_name} active page to a "
                "closed or invalid page."
            )
        is_allowed = getattr(self.adapter, "is_page_allowed", None)
        if is_allowed is not None and is_allowed(page) is False:
            raise ValueError(
                f"[midscene] Cannot set {self.agent_name} active page to an "
                "out-of-scope page."
            )

        self._set_active_page(page)
        try:
            await _maybe_await(self.adapter.bring_to_front(page))
        except Exception as error:
            self.debug(f"failed to bring page to front: {error}")

    async def set_active_page_by_selector(
        self, selector: Dict[str, Any]
    ) -> Dict[str, Any]:
        selector_index = selector.get("index")
        title = _normalize_optional_text(selector.get("title"))
        url = _normalize_optional_text(selector.get("url"))

        if selector_index is None and not title and not url:
            raise ValueError(
                "[midscene] SetActivePage requires index, title, or url for "
                f"{self.agent_name}."
            )

        pages = await self.open_pages()

        if selector_index is not None:
            page = (
                pages[selector_index]
                if 0 <= selector_index < len(pages)
                else None
            )
            if page is None or self.adapter.is_page_closed(page):
                raise ValueError(
                    f"[midscene] Cannot find {self.agent_name} page with index "
                    f"{selector_index}. Available page indexes: "
                    f"{', '.join(str(i) for i in range(len(pages)))}"
                )

            summary = await self._try_page_summary(page, selector_index, True)
            if summary is None:
                raise RuntimeError(
                    f"[midscene] {self.agent_name} page at index "
                    f"{selector_index} closed while reading its metadata. Run "
                    "ListBrowserPages again."
                )
            if not _page_summary_matches(summary, title, url):
                text_selector = _describe_selector(
                    {"title": selector.get("title"), "url": selector.get("url")}
                )
                raise ValueError(
                    f"[midscene] {self.agent_name} page at index "
                    f"{selector_index} does not match {text_selector}. Run "
                    "ListBrowserPages again before selecting a page."
                )

            await self.set_active_page(page)
            return summary

        matched: List[Dict[str, Any]] = []
        for index, page in enumerate(pages):
            if self.adapter.is_page_closed(page):
                continue
            summary = await self._try_page_summary(page, index, False)
            if summary is not None and _page_summary_matches(summary, title, url):
                matched.append({"page": page, "summary": summary})

        if not matched:
            raise ValueError(
                f"[midscene] Cannot find {self.agent_name} page matching "
                f"{_describe_selector(selector)}."
            )
        if len(matched) > 1:
            raise ValueError(
                f"[midscene] Multiple {self.agent_name} pages matched "
                f"{_describe_selector(selector)}. Use ListBrowserPages and "
                "pass an index to SetActivePage."
            )

        page = matched[0]["page"]
        summary = matched[0]["summary"]
        await self.set_active_page(page)
        return {**summary, "active": True}

    async def wait_for_new_page(
        self,
        action: Optional[Callable[[], Any]] = None,
        opts: Optional[Dict[str, Any]] = None,
    ) -> Any:
        waiter = self._create_new_page_waiter((opts or {}).get("timeout"))
        try:
            if action is not None:
                await _maybe_await(action())
            return await waiter["promise"]
        except BaseException:
            waiter["dispose"]()
            raise

    def destroy(self) -> None:
        _schedule(self.adapter.off_new_page(self._new_page_handler))

    async def open_pages(self) -> List[Any]:
        pages = await _maybe_await(self.adapter.pages())
        return [page for page in pages if not self.adapter.is_page_closed(page)]

    async def _try_page_summary(
        self, page: Any, index: int, active: bool
    ) -> Optional[Dict[str, Any]]:
        try:
            summary = {
                "index": index,
                "active": active,
                "title": await _maybe_await(self.adapter.page_title(page)),
                "url": self.adapter.page_url(page),
            }
            return None if self.adapter.is_page_closed(page) else summary
        except Exception:
            if self.adapter.is_page_closed(page):
                return None
            raise

    async def _on_new_page_event(self, event: Any) -> None:
        await self._follow_new_page(event)

    async def _follow_new_page(self, event: Any) -> None:
        if not self._is_new_page_event(event):
            return
        try:
            page = await _maybe_await(self.adapter.resolve_new_page(event))
            if page is not None:
                await self.set_active_page(page)
        except Exception as error:
            self.debug(f"failed to follow new page: {error}")

    def _is_new_page_event(self, event: Any) -> bool:
        is_new_page_event = getattr(self.adapter, "is_new_page_event", None)
        if is_new_page_event is None:
            return True
        return bool(is_new_page_event(event))

    def _create_new_page_waiter(
        self, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        timeout = self.new_page_timeout if timeout is None else timeout
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        settled = False
        timer: Optional[asyncio.TimerHandle] = None

        def dispose() -> None:
            self.adapter.off_new_page(handler)
            if timer is not None:
                timer.cancel()

        async def handler(event: Any) -> None:
            nonlocal settled
            if settled or not self._is_new_page_event(event):
                return
            settled = True
            dispose()
            try:
                page = await _maybe_await(self.adapter.resolve_new_page(event))
                if page is None:
                    raise RuntimeError("new target did not resolve to a page")
                if not future.done():
                    future.set_result(page)
            except BaseException as error:
                if not future.done():
                    future.set_exception(error)

        def on_timeout() -> None:
            nonlocal settled
            if settled:
                return
            settled = True
            dispose()
            if not future.done():
                future.set_exception(
                    TimeoutError(
                        "[midscene] Timed out waiting for a new "
                        f"{self.agent_name} page after {timeout}ms."
                    )
                )

        timer = loop.call_later(timeout / 1000, on_timeout)
        self.adapter.on_new_page(handler)

        return {"promise": future, "dispose": dispose}


__all__ = [
    "BrowserAgent",
    "BrowserAgentAdapter",
    "BrowserAgentPageScope",
    "BrowserAgentPageSelector",
    "BrowserAgentPageSummary",
    "BrowserAgentRuntimeOptions",
    "BrowserPageManager",
    "DEFAULT_NEW_PAGE_TIMEOUT",
    "ResolvedBrowserAgentRuntimeOptions",
    "WebAgentCore",
    "resolve_browser_agent_runtime_options",
]
