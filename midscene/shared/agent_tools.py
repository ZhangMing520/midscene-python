"""Agent tools exposed to CLI / MCP clients (upstream shared/agent-tools).

A tool is a small dict: {name, description, inputSchema, handler}. The handler
takes the tool arguments and returns JSON-serializable data.
"""

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _dataclass_payload(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _dataclass_payload(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


class AgentTools:
    """Lazily creates one browser Agent and exposes it as MCP tools."""

    def __init__(self, page_factory: Optional[Callable[..., Awaitable[Any]]] = None):
        self._page_factory = page_factory or _default_page_factory
        self._agent: Any = None
        self._page: Any = None

    # -- lifecycle ---------------------------------------------------------

    async def ensure_agent(self, arguments: Dict[str, Any]) -> Any:
        if self._agent is not None:
            return self._agent
        from midscene.core.agent.agent import Agent

        self._page = await self._page_factory(
            browser=arguments.get("browser") or "playwright",
            headless=bool(arguments.get("headless", True)),
        )
        try:
            url = arguments.get("url")
            if url:
                await self._page.navigate_to(url)
            self._agent = Agent(self._page)
        except Exception:
            await self.close()  # do not leak the browser on a failed start
            raise
        return self._agent

    async def close(self) -> None:
        agent, page = self._agent, self._page
        self._agent = self._page = None
        if agent is not None:
            try:
                await agent.destroy()
            except Exception:
                pass
        if page is not None:
            try:
                result = page.close()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass

    # -- tool definitions --------------------------------------------------

    def tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            self._tool(
                "midscene_init",
                "Open a browser (or reuse the current one) and start a Midscene agent. Call this before other tools.",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Page to open first"},
                        "browser": {
                            "type": "string",
                            "enum": ["playwright", "selenium"],
                            "description": "Browser driver (default playwright)",
                        },
                        "headless": {"type": "boolean", "default": True},
                    },
                },
                self._handle_init,
            ),
            self._tool(
                "midscene_act",
                "Run a natural-language action plan against the current page (aiAct).",
                {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "What to do"},
                    },
                    "required": ["prompt"],
                },
                self._handle_act,
            ),
            self._tool(
                "midscene_query",
                "Extract structured data from the page; prompt may be a string or a JSON schema of fields.",
                {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "description": "Data demand string or object of field -> description",
                        },
                    },
                    "required": ["prompt"],
                },
                self._handle_query,
            ),
            self._tool(
                "midscene_assert",
                "Check whether a statement about the page holds (aiAssert).",
                {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Statement to verify"},
                    },
                    "required": ["prompt"],
                },
                self._handle_assert,
            ),
            self._tool(
                "midscene_locate",
                "Locate one element by description and return its center and rect.",
                {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Element description"},
                    },
                    "required": ["prompt"],
                },
                self._handle_locate,
            ),
            self._tool(
                "web_tabs",
                "List browser tabs with stable IDs, titles, URLs and the active tab.",
                {"type": "object", "properties": {}},
                self._handle_tabs,
            ),
            self._tool(
                "web_switch-tab",
                "Switch to an existing tab by ID. Later commands use this tab.",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Tab ID returned by web_tabs"},
                    },
                    "required": ["id"],
                },
                self._handle_switch_tab,
            ),
            self._tool(
                "midscene_close",
                "Close the agent and the browser started by midscene_init.",
                {"type": "object", "properties": {}},
                self._handle_close,
            ),
        ]

    @staticmethod
    def _tool(name, description, input_schema, handler) -> Dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler,
        }

    # -- handlers ----------------------------------------------------------

    async def _handle_init(self, arguments: Dict[str, Any]) -> Any:
        agent = await self.ensure_agent(arguments)
        tabs = await self._list_tabs()
        return {"status": "ready", "tabs": tabs, "agent": type(agent).__name__}

    async def _handle_act(self, arguments: Dict[str, Any]) -> Any:
        agent = await self.ensure_agent(arguments)
        return await agent.ai_act(arguments["prompt"]) or "done"

    async def _handle_query(self, arguments: Dict[str, Any]) -> Any:
        agent = await self.ensure_agent(arguments)
        return await agent.ai_query(arguments["prompt"])

    async def _handle_assert(self, arguments: Dict[str, Any]) -> Any:
        agent = await self.ensure_agent(arguments)
        result = await agent.ai_assert(arguments["prompt"])
        return _dataclass_payload(result)

    async def _handle_locate(self, arguments: Dict[str, Any]) -> Any:
        agent = await self.ensure_agent(arguments)
        result = await agent.ai_locate(arguments["prompt"])
        return _dataclass_payload(result)

    async def _handle_tabs(self, arguments: Dict[str, Any]) -> Any:
        if self._page is None:
            raise RuntimeError("call midscene_init first")
        return await self._list_tabs()

    async def _handle_switch_tab(self, arguments: Dict[str, Any]) -> Any:
        if self._page is None:
            raise RuntimeError("call midscene_init first")
        tab_id = str(arguments["id"])
        await self._page.switch_tab(tab_id)
        return {"status": "ok", "id": tab_id}

    async def _handle_close(self, arguments: Dict[str, Any]) -> Any:
        await self.close()
        return {"status": "closed"}

    async def _list_tabs(self) -> Any:
        list_tabs = getattr(self._page, "list_tabs", None)
        if list_tabs is None:
            return []
        return await list_tabs()


async def _default_page_factory(browser: str = "playwright", headless: bool = True):
    if browser == "selenium":
        from midscene.web_integration.selenium_page import SeleniumWebPage

        return SeleniumWebPage.create(headless=headless)
    if browser != "playwright":
        raise ValueError(f"Unsupported browser: {browser}")
    from midscene.web_integration.playwright_page import PlaywrightWebPage

    return await PlaywrightWebPage.create(headless=headless)


__all__ = ["AgentTools"]