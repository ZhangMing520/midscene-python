"""Port of upstream packages/web-integration/tests/unit-test/browser-page-manager.test.ts."""

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import pytest

from midscene.web_integration.common.browser_agent import (
    BrowserAgentRuntimeOptions,
    BrowserPageManager,
    resolve_browser_agent_runtime_options,
)
from midscene.web_integration.common.browser_page_actions import (
    append_browser_agent_page_actions,
    create_browser_agent_page_actions,
)


class _Page:
    def __init__(
        self,
        id: str,
        title: str | None = None,
        url: str | None = None,
    ):
        self.id = id
        self.title = id if title is None else title
        self.url = f"https://example.com/{id}" if url is None else url
        self.closed = False
        self.bring_to_front_calls = 0

    def bring_to_front(self) -> None:
        self.bring_to_front_calls += 1


class _Adapter:
    def __init__(
        self,
        pages: list[_Page],
        new_page: _Page,
        handlers: set,
        page_title: Callable[[_Page], Any],
        page_url: Callable[[_Page], str],
    ):
        self._pages = pages
        self._new_page = new_page
        self._handlers = handlers
        self._page_title = page_title
        self._page_url = page_url

    def pages(self) -> list[_Page]:
        return self._pages

    async def new_page(self) -> _Page:
        self._pages.append(self._new_page)
        return self._new_page

    def is_page_closed(self, page: _Page) -> bool:
        return bool(page.closed)

    def bring_to_front(self, page: _Page) -> None:
        page.bring_to_front()

    def page_title(self, page: _Page) -> Any:
        return self._page_title(page)

    def page_url(self, page: _Page) -> str:
        return self._page_url(page)

    def on_new_page(self, handler: Callable[[Any], Any]) -> None:
        self._handlers.add(handler)

    def off_new_page(self, handler: Callable[[Any], Any]) -> None:
        self._handlers.discard(handler)

    def is_new_page_event(self, event: Any) -> bool:
        return event["kind"] == "page"

    def resolve_new_page(self, event: Any) -> _Page | None:
        return event.get("page")


class _ManagerContext:
    def __init__(
        self,
        manager: BrowserPageManager,
        handlers: set,
        debug_calls: list,
        new_page: _Page,
        get_active_page: Callable[[], _Page],
    ):
        self.manager = manager
        self.handlers = handlers
        self.debug_calls = debug_calls
        self.new_page = new_page
        self._get_active_page = get_active_page

    @property
    def active_page(self) -> _Page:
        return self._get_active_page()

    async def emit(self, event: Any) -> None:
        for handler in list(self.handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                await result


def create_page(
    id: str,
    options: dict | None = None,
) -> _Page:
    options = options or {}
    return _Page(id, options.get("title"), options.get("url"))


def create_manager(
    options: dict | None = None,
) -> _ManagerContext:
    options = options or {}
    pages = options.get("pages")
    active_page = options.get("active_page")
    if active_page is None:
        active_page = pages[0] if pages else create_page("initial")
    if pages is None:
        pages = [active_page]

    handlers: set = set()
    debug_calls: list[str] = []
    new_page = options.get("new_page") or create_page("created")
    page_title = options.get("page_title") or (lambda page: page.title)
    page_url = options.get("page_url") or (lambda page: page.url)

    adapter = _Adapter(pages, new_page, handlers, page_title, page_url)

    def get_active_page() -> _Page:
        return active_page

    def set_active_page_value(page: _Page) -> None:
        nonlocal active_page
        active_page = page

    manager = BrowserPageManager(
        "TestBrowserAgent",
        adapter,
        get_active_page,
        set_active_page_value,
        auto_follow_new_page=options.get("auto_follow_new_page", False),
        new_page_timeout=50,
        debug=debug_calls.append,
    )

    return _ManagerContext(manager, handlers, debug_calls, new_page, get_active_page)


@pytest.mark.asyncio
async def test_sets_the_created_page_as_active_page():
    """sets the created page as active page."""
    ctx = create_manager()

    page = await ctx.manager.new_page()

    assert page.id == "created"
    assert ctx.active_page is page
    assert page.bring_to_front_calls == 1


@pytest.mark.asyncio
async def test_lists_browser_pages_with_the_active_page_marker():
    """lists browser pages with the active page marker."""
    initial = create_page(
        "initial", {"title": "Home", "url": "https://example.com/home"}
    )
    docs = create_page("docs", {"title": "Docs", "url": "https://example.com/docs"})
    ctx = create_manager({"pages": [initial, docs], "active_page": docs})

    summaries = await ctx.manager.page_summaries()

    assert summaries == [
        {
            "index": 0,
            "active": False,
            "title": "Home",
            "url": "https://example.com/home",
        },
        {
            "index": 1,
            "active": True,
            "title": "Docs",
            "url": "https://example.com/docs",
        },
    ]


@pytest.mark.asyncio
async def test_reports_page_metadata_failures_instead_of_returning_blank_values():
    """reports page metadata failures instead of returning blank values."""

    def page_title(_page):
        raise RuntimeError("title unavailable")

    ctx = create_manager({"page_title": page_title})

    with pytest.raises(RuntimeError, match="title unavailable"):
        await ctx.manager.page_summaries()


@pytest.mark.asyncio
async def test_skips_a_page_that_closes_while_its_title_is_being_read():
    """skips a page that closes while its title is being read."""
    closing = create_page("closing")
    docs = create_page("docs", {"title": "Docs"})

    async def page_title(page):
        if page is closing:
            closing.closed = True
            raise RuntimeError("page closed")
        return page.title

    ctx = create_manager({"pages": [closing, docs], "page_title": page_title})

    assert await ctx.manager.page_summaries() == [
        {
            "index": 0,
            "active": False,
            "title": "Docs",
            "url": "https://example.com/docs",
        }
    ]
    summary = await ctx.manager.set_active_page_by_selector({"title": "docs"})
    assert summary["title"] == "Docs"
    assert summary["active"] is True

    closing_during_selection = create_page("closing")

    async def selector_page_title(page):
        if page is closing_during_selection:
            closing_during_selection.closed = True
            raise RuntimeError("page closed")
        return page.title

    selector_ctx = create_manager(
        {
            "pages": [closing_during_selection, docs],
            "page_title": selector_page_title,
        }
    )
    summary = await selector_ctx.manager.set_active_page_by_selector({"title": "docs"})
    assert summary["title"] == "Docs"
    assert summary["active"] is True


@pytest.mark.asyncio
async def test_reports_when_a_page_closes_while_its_details_are_being_read():
    """reports when a page closes while its details are being read."""
    closing = create_page("closing")

    async def page_title(page):
        page.closed = True
        raise RuntimeError("page closed")

    ctx = create_manager({"pages": [closing], "page_title": page_title})

    with pytest.raises(RuntimeError) as error:
        await ctx.manager.page_summary_by_index(0)
    assert str(error.value) == (
        "[midscene] TestBrowserAgent page at index 0 closed while reading its "
        "metadata. Run ListBrowserPages again."
    )


@pytest.mark.asyncio
async def test_sets_the_active_page_by_selector():
    """sets the active page by selector."""
    initial = create_page(
        "initial", {"title": "Home", "url": "https://example.com/home"}
    )
    docs = create_page("docs", {"title": "Docs", "url": "https://example.com/docs"})
    ctx = create_manager({"pages": [initial, docs]})

    summary = await ctx.manager.set_active_page_by_selector({"title": "docs"})

    assert ctx.active_page is docs
    assert summary == {
        "index": 1,
        "active": True,
        "title": "Docs",
        "url": "https://example.com/docs",
    }
    assert docs.bring_to_front_calls == 1


@pytest.mark.asyncio
async def test_validates_title_and_url_when_they_accompany_an_index_selector():
    """validates title and url when they accompany an index selector."""
    initial = create_page(
        "initial", {"title": "Home", "url": "https://example.com/home"}
    )
    docs = create_page("docs", {"title": "Docs", "url": "https://example.com/docs"})
    ctx = create_manager({"pages": [initial, docs]})

    summary = await ctx.manager.set_active_page_by_selector(
        {"index": 1, "title": "docs", "url": "/docs"}
    )
    assert summary["index"] == 1
    assert summary["title"] == "Docs"

    with pytest.raises(ValueError) as error:
        await ctx.manager.set_active_page_by_selector({"index": 0, "title": "Docs"})
    assert str(error.value) == (
        "[midscene] TestBrowserAgent page at index 0 does not match title "
        '"Docs". Run ListBrowserPages again before selecting a page.'
    )
    assert ctx.active_page is docs
    assert initial.bring_to_front_calls == 0


@pytest.mark.asyncio
async def test_rejects_ambiguous_title_or_url_selectors():
    """rejects ambiguous title or url selectors."""
    first = create_page("first", {"title": "Docs", "url": "https://example.com/docs"})
    second = create_page(
        "second", {"title": "API Docs", "url": "https://example.com/api"}
    )
    ctx = create_manager({"pages": [first, second]})

    with pytest.raises(ValueError) as error:
        await ctx.manager.set_active_page_by_selector({"title": "docs"})
    assert str(error.value) == (
        '[midscene] Multiple TestBrowserAgent pages matched title "docs". '
        "Use ListBrowserPages and pass an index to SetActivePage."
    )


@pytest.mark.asyncio
async def test_creates_browser_page_actions_for_ai_page_selection():
    """creates browser page actions for AI page selection."""
    initial = create_page(
        "initial", {"title": "Home", "url": "https://example.com/home"}
    )
    docs = create_page("docs", {"title": "Docs", "url": "https://example.com/docs"})
    ctx = create_manager({"pages": [initial, docs]})
    feedback = {}

    actions = create_browser_agent_page_actions(
        lambda: ctx.manager, lambda text: feedback.__setitem__("text", text)
    )

    assert [action.name for action in actions] == [
        "ListBrowserPages",
        "GetBrowserPageInfo",
        "SetActivePage",
    ]
    summaries = await actions[0].execute(None, None, None)
    assert summaries == [
        {
            "index": 0,
            "active": True,
            "title": "Home",
            "url": "https://example.com/home",
        },
        {
            "index": 1,
            "active": False,
            "title": "Docs",
            "url": "https://example.com/docs",
        },
    ]
    assert feedback["text"] == (
        "ListBrowserPages 0-1 of 2; active 0 (0-based). Use SetActivePage.\n"
        "*0|Home|https://example.com/home\n"
        " 1|Docs|https://example.com/docs"
    )

    await actions[2].execute({"index": 1}, None, None)
    assert ctx.active_page is docs


@pytest.mark.asyncio
async def test_keeps_distinguishing_page_details_when_pages_share_long_prefixes():
    """keeps distinguishing page details when pages share long prefixes."""
    pages = [
        create_page(
            f"page-{index}",
            {
                "title": f"{'shared title ' * 20}unique-title-{index}",
                "url": (f"https://example.com/{'shared-path/' * 50}unique-url-{index}"),
            },
        )
        for index in range(8)
    ]
    ctx = create_manager({"pages": pages, "active_page": pages[2]})
    feedback = {}
    actions = create_browser_agent_page_actions(
        lambda: ctx.manager, lambda text: feedback.__setitem__("text", text)
    )

    await actions[0].execute(None, None, None)

    text = feedback["text"]
    for index in range(len(pages)):
        marker = "*" if index == 2 else " "
        assert f"{marker}{index}|" in text
        assert f"unique-title-{index}" in text
        assert f"unique-url-{index}" in text
    assert len(text) > 500


@pytest.mark.asyncio
async def test_returns_full_page_info_without_switching_pages_and_forwards_useful_details():
    """returns full page info without switching pages and forwards useful details."""
    initial = create_page("initial")
    full_title = f"{'title ' * 30}unique-title-tail"
    full_url = f"https://example.com/{'long-path/' * 60}unique-url-tail"
    details = create_page("details", {"title": full_title, "url": full_url})
    ctx = create_manager({"pages": [initial, details]})
    feedback = {}
    actions = create_browser_agent_page_actions(
        lambda: ctx.manager, lambda text: feedback.__setitem__("text", text)
    )

    summary = await actions[1].execute({"index": 1}, None, None)
    assert summary == {
        "index": 1,
        "active": False,
        "title": full_title,
        "url": full_url,
    }
    assert ctx.active_page is initial
    assert "unique-title-tail" in feedback["text"]
    assert "unique-url-tail" in feedback["text"]


@pytest.mark.asyncio
async def test_forwards_an_extreme_url_without_truncating_planning_feedback():
    """forwards an extreme URL without truncating planning feedback."""
    long_url = f"https://example.com/{'x' * 5000}unique-url-tail"
    page = create_page("long-url", {"url": long_url})
    ctx = create_manager({"pages": [page]})
    feedback = {}
    actions = create_browser_agent_page_actions(
        lambda: ctx.manager, lambda text: feedback.__setitem__("text", text)
    )

    summary = await actions[1].execute({"index": 0}, None, None)
    assert summary["url"] == long_url
    assert f"URL: {long_url}" in feedback["text"]


@pytest.mark.asyncio
async def test_paginates_large_page_lists_without_losing_page_identities():
    """paginates large page lists without losing page identities."""
    pages = [create_page(f"page-{index}") for index in range(100)]
    ctx = create_manager({"pages": pages, "active_page": pages[99]})
    feedback = {}
    actions = create_browser_agent_page_actions(
        lambda: ctx.manager, lambda text: feedback.__setitem__("text", text)
    )

    first_page = await actions[0].execute(None, None, None)
    assert len(first_page) == 8
    assert "Next: ListBrowserPages({offset:8})" in feedback["text"]
    assert " 7|page-7|" in feedback["text"]

    last_page = await actions[0].execute({"offset": 96}, None, None)
    assert [item["index"] for item in last_page] == [96, 97, 98, 99]
    assert "*99|page-99|" in feedback["text"]

    with pytest.raises(ValueError, match="offset 100 is out of range"):
        await actions[0].execute({"offset": 100}, None, None)


def test_keeps_custom_actions_ahead_of_browser_page_actions():
    """keeps custom actions ahead of browser page actions."""
    custom_action = {
        "name": "SetActivePage",
        "description": "custom action",
        "call": lambda *args: None,
    }
    browser_actions = create_browser_agent_page_actions(
        lambda: create_manager().manager
    )

    actions = append_browser_agent_page_actions([custom_action], browser_actions)

    assert [
        action["name"] if isinstance(action, dict) else action.name
        for action in actions
    ] == [
        "SetActivePage",
        "ListBrowserPages",
        "GetBrowserPageInfo",
    ]
    assert actions[0] is custom_action


@pytest.mark.asyncio
async def test_auto_follows_matching_new_page_events():
    """auto-follows matching new page events."""
    ctx = create_manager({"auto_follow_new_page": True})
    next_page = create_page("next")

    await ctx.emit({"kind": "worker"})
    assert ctx.active_page.id == "initial"

    await ctx.emit({"kind": "page", "page": next_page})
    assert ctx.active_page is next_page
    assert next_page.bring_to_front_calls == 1


@pytest.mark.asyncio
async def test_waits_for_the_next_page_without_switching_active_page():
    """waits for the next page without switching active page."""
    ctx = create_manager()
    next_page = create_page("next")

    waiting = asyncio.create_task(ctx.manager.wait_for_new_page())
    await asyncio.sleep(0)
    await ctx.emit({"kind": "worker"})
    await ctx.emit({"kind": "page", "page": next_page})

    assert await waiting is next_page
    assert ctx.active_page.id == "initial"


def test_removes_the_auto_follow_listener_on_destroy():
    """removes the auto-follow listener on destroy."""
    ctx = create_manager({"auto_follow_new_page": True})

    assert len(ctx.handlers) == 1
    ctx.manager.destroy()
    assert len(ctx.handlers) == 0


@pytest.mark.asyncio
async def test_rejects_closed_pages():
    """rejects closed pages."""
    ctx = create_manager()
    closed_page = create_page("closed")
    closed_page.closed = True

    with pytest.raises(ValueError) as error:
        await ctx.manager.set_active_page(closed_page)
    assert str(error.value) == (
        "[midscene] Cannot set TestBrowserAgent active page to a closed or "
        "invalid page."
    )


def test_keeps_page_mode_locked_by_default():
    """keeps page mode locked by default."""
    resolved = resolve_browser_agent_runtime_options(
        {"agent_name": "TestPageAgent", "page_scope": "page"}
    )

    assert asdict(resolved) == {
        "page_scope": "page",
        "force_same_tab_navigation": True,
        "auto_follow_new_page": False,
        "new_page_timeout": 5000,
    }


def test_keeps_browser_mode_browser_controlled_by_default():
    """keeps browser mode browser-controlled by default."""
    resolved = resolve_browser_agent_runtime_options(
        {"agent_name": "TestBrowserAgent", "page_scope": "browser"}
    )

    assert asdict(resolved) == {
        "page_scope": "browser",
        "force_same_tab_navigation": False,
        "auto_follow_new_page": False,
        "new_page_timeout": 5000,
    }


def test_rejects_auto_follow_in_page_mode():
    """rejects auto-follow in page mode."""
    with pytest.raises(ValueError, match="autoFollowNewPage requires browser mode"):
        resolve_browser_agent_runtime_options(
            BrowserAgentRuntimeOptions(
                agent_name="TestPageAgent",
                page_scope="page",
                auto_follow_new_page=True,
            )
        )


def test_rejects_same_tab_forcing_in_browser_mode():
    """rejects same-tab forcing in browser mode."""
    with pytest.raises(
        ValueError, match="forceSameTabNavigation cannot be used in browser mode"
    ):
        resolve_browser_agent_runtime_options(
            BrowserAgentRuntimeOptions(
                agent_name="TestBrowserAgent",
                page_scope="browser",
                force_same_tab_navigation=False,
            )
        )
