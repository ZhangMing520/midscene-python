"""Shared browser tab tools (upstream web-integration/agent-tools-tabs.ts)."""

import inspect
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from midscene.shared.agent_tools.types import (
    ToolDefinition,
    ToolResult,
    schema_field,
)


class BrowserTabSummary(TypedDict):
    """Stable summary of one browser tab."""

    id: str
    title: str
    url: str
    active: bool


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _page_member(page: Any, *names: str) -> Any:
    for name in names:
        value = getattr(page, name, None)
        if value is not None:
            return value
    return None


def get_target_id(page: Any) -> Optional[str]:
    """Return the Chrome target id exposed by a page, or None.

    Puppeteer pages expose ``target()._targetId``.  Python drivers without that
    private field can set ``_midscene_target_id`` on the page instead.
    """
    cached = getattr(page, "_midscene_target_id", None)
    if isinstance(cached, str) and cached:
        return cached

    target_fn = getattr(page, "target", None)
    if not callable(target_fn):
        return None
    target = target_fn()
    if inspect.isawaitable(target):
        return None
    if isinstance(target, dict):
        value = target.get("_targetId")
    else:
        value = getattr(target, "_targetId", None) if target is not None else None
    return value if isinstance(value, str) and value else None


def require_target_id(page: Any) -> str:
    target_id = get_target_id(page)
    if not target_id:
        raise RuntimeError("Chrome did not expose a target ID for this page.")
    return target_id


def page_url(page: Any) -> str:
    value = _page_member(page, "url")
    if callable(value):
        value = value()
    return value or ""


async def page_title(page: Any) -> str:
    value = _page_member(page, "title")
    if callable(value):
        value = value()
    value = await _maybe_await(value)
    return value or ""


def is_page_closed(page: Any) -> bool:
    value = _page_member(page, "is_closed", "isClosed")
    if callable(value):
        value = value()
    return bool(value)


def create_tab_tools(
    adapter: Dict[str, Callable[..., Awaitable[Any]]]
) -> List[ToolDefinition]:
    """Build the ``web_tabs`` / ``web_switch-tab`` tools over a tab adapter."""

    async def list_tabs(_args: Dict[str, Any]) -> ToolResult:
        tabs = await adapter["list"]()
        return ToolResult(
            [{"type": "text", "text": json.dumps(tabs, ensure_ascii=False)}]
        )

    async def switch_tab(args: Dict[str, Any]) -> ToolResult:
        tab_id = args.get("id")
        await adapter["select"](tab_id)
        return ToolResult(
            [{"type": "text", "text": f"Switched to tab: {tab_id}"}]
        )

    return [
        ToolDefinition(
            name="web_tabs",
            description=(
                "List browser tabs with stable IDs, titles, URLs and the "
                "active tab."
            ),
            schema={},
            handler=list_tabs,
        ),
        ToolDefinition(
            name="web_switch-tab",
            description=(
                "Switch to an existing tab by ID. Subsequent commands use "
                "this tab. Use tabs to find IDs."
            ),
            schema={
                "id": schema_field("string", "Tab ID returned by tabs"),
            },
            handler=switch_tab,
        ),
    ]


def create_puppeteer_tab_tools(
    ensure_agent: Callable[[], Awaitable[Any]],
    save_target: Callable[[str], Any],
) -> List[ToolDefinition]:
    """Build tab tools for a puppeteer-style agent and its target store."""

    async def list_tabs() -> List[BrowserTabSummary]:
        agent = await ensure_agent()
        pages = [
            page
            for page in await _maybe_await(agent.pages())
            if not is_page_closed(page)
        ]
        summaries: List[BrowserTabSummary] = []
        for page in pages:
            summaries.append(
                {
                    "id": require_target_id(page),
                    "title": await page_title(page),
                    "url": page_url(page),
                    "active": page is getattr(agent, "active_page", None),
                }
            )
        return summaries

    async def select_tab(tab_id: str) -> None:
        agent = await ensure_agent()
        pages = [
            page
            for page in await _maybe_await(agent.pages())
            if not is_page_closed(page)
        ]
        page = next(
            (item for item in pages if get_target_id(item) == tab_id), None
        )
        if page is None:
            raise ValueError(
                f"Tab {tab_id} does not exist or has closed. Run tabs again."
            )
        previous_page = getattr(agent, "active_page", None)
        await _maybe_await(agent.set_active_page(page))
        try:
            await _maybe_await(save_target(tab_id))
        except Exception as error:
            try:
                await _maybe_await(agent.set_active_page(previous_page))
            except Exception as rollback_error:
                raise RuntimeError(
                    "Failed to save the selected tab and restore the previous "
                    f"page. ({rollback_error})"
                ) from error
            raise

    return create_tab_tools({"list": list_tabs, "select": select_tab})


__all__ = [
    "BrowserTabSummary",
    "create_puppeteer_tab_tools",
    "create_tab_tools",
    "get_target_id",
    "is_page_closed",
    "page_title",
    "page_url",
    "require_target_id",
]
