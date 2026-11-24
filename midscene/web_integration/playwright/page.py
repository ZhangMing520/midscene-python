"""
Playwright integration for Midscene

The generic click/input/scroll/cache-feature primitives live in
``midscene.web_integration.common.browser_page_actions`` and the browser agent
helpers in ``midscene.web_integration.common.browser_agent_utils``; this module
owns only the Playwright-specific lifecycle and DOM extraction.
"""

import asyncio  # noqa: F401 - callers patch this module's asyncio.sleep
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from midscene.core.types import (
    AbstractInterface,
    FileChooserHandler,
    FileChooserRegistration,
    InterfaceType,
    NodeType,
    Rect,
    Size,
    UIContext,
    UINode,
    UITree,
)
from midscene.web_integration.common.browser_agent_utils import (
    apply_force_chrome_select_rendering,
    get_page_size,
    take_screenshot_base64,
)
from midscene.web_integration.common.browser_page_actions import (
    INPUT_STRATEGIES,  # noqa: F401 - re-exported for compatibility
    BrowserPageActionsMixin,
    _resolve_text_input_options,  # noqa: F401 - re-exported for compatibility
)
from midscene.web_integration.common.cache_helper import judge_order_sensitive
from midscene.web_integration.web_element import PlaywrightElement


class WebPage(BrowserPageActionsMixin, AbstractInterface):
    """Playwright page interface (upstream playwright/page.ts WebPage)."""

    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        browser: Browser,
        playwright: Any | None = None,
        keyboard_type_delay: float | None = None,
        input_strategy: str | None = None,
        force_same_tab_navigation: bool = True,
        auto_follow_new_page: bool = False,
        force_chrome_select_rendering: bool = True,
    ):
        """Initialize with Playwright page

        Args:
            page: Playwright page instance
            context: Browser context
            browser: Browser instance
            playwright: Playwright instance started by create(), stopped on close
            keyboard_type_delay: Per-character typing delay in milliseconds
            input_strategy: "legacy" | "sequential" | "bulk"
            force_same_tab_navigation: Keep target=_blank navigation in this tab
            auto_follow_new_page: Switch self.page to the newest opened page
            force_chrome_select_rendering: Force base-select rendering for selects
        """
        self.page = page
        self.context = context
        self.browser = browser
        self._playwright = playwright
        self.keyboard_type_delay = keyboard_type_delay
        self.input_strategy = input_strategy
        self.force_same_tab_navigation = bool(force_same_tab_navigation)
        self.auto_follow_new_page = bool(auto_follow_new_page)
        self._force_chrome_select_rendering = bool(force_chrome_select_rendering)
        self._initial_page = page
        self._popup_handler = None
        self._new_page_handler = None

        if self.auto_follow_new_page:
            if self.force_same_tab_navigation:
                logger.warning(
                    "autoFollowNewPage cannot be used with "
                    "forceSameTabNavigation: true; forceSameTabNavigation is "
                    "disabled."
                )
                self.force_same_tab_navigation = False
            self._new_page_handler = self._on_new_page
            self.context.on("page", self._new_page_handler)
        elif self.force_same_tab_navigation:
            self._popup_handler = self._on_popup
            self.page.on("popup", self._popup_handler)

    @classmethod
    async def create(
        cls,
        headless: bool = False,
        viewport_size: tuple[int, int] = (1920, 1080),
        user_data_dir: str | None = None,
        user_agent: str | None = None,
        device_scale_factor: float | None = None,
        accept_insecure_certs: bool = False,
        cookie_file: str | None = None,
        extra_http_headers: dict[str, str] | None = None,
        keyboard_type_delay: float | None = None,
        input_strategy: str | None = None,
        force_same_tab_navigation: bool = True,
        auto_follow_new_page: bool = False,
        force_chrome_select_rendering: bool = True,
        **browser_options,
    ) -> "WebPage":
        """Create new Playwright page instance

        Args:
            headless: Run in headless mode
            viewport_size: Browser viewport size
            user_data_dir: Browser user data directory
            user_agent: Browser User-Agent string
            device_scale_factor: Device pixel ratio (upstream deviceScaleFactor)
            accept_insecure_certs: Ignore HTTPS errors
            cookie_file: JSON file with cookies loaded before navigation
            extra_http_headers: Extra HTTP headers for every request
            keyboard_type_delay: Per-character typing delay in milliseconds
            input_strategy: "legacy" | "sequential" | "bulk"
            force_same_tab_navigation: Keep target=_blank navigation in this tab
            auto_follow_new_page: Switch to the newest opened page
            force_chrome_select_rendering: Force base-select rendering for selects
            **browser_options: Additional browser launch options (e.g. args)

        Returns:
            PlaywrightWebPage instance
        """
        playwright = await async_playwright().start()

        launch_options = {"headless": headless, **browser_options}

        if user_data_dir:
            launch_options["user_data_dir"] = user_data_dir

        browser = await playwright.chromium.launch(**launch_options)

        context_options: dict[str, Any] = {
            "viewport": {
                "width": viewport_size[0],
                "height": viewport_size[1],
            },
            "user_agent": user_agent,
            "ignore_https_errors": accept_insecure_certs,
        }
        if device_scale_factor is not None:
            context_options["device_scale_factor"] = float(device_scale_factor)
        if extra_http_headers:
            context_options["extra_http_headers"] = {
                str(key): str(value) for key, value in extra_http_headers.items()
            }
        context = await browser.new_context(**context_options)

        if cookie_file:
            import json as _json

            raw = _json.loads(Path(cookie_file).read_text(encoding="utf-8"))
            cookies = raw.get("cookies") if isinstance(raw, dict) else raw
            if isinstance(cookies, list) and cookies:
                await context.add_cookies(cookies)

        page = await context.new_page()

        instance = cls(
            page,
            context,
            browser,
            playwright,
            keyboard_type_delay=keyboard_type_delay,
            input_strategy=input_strategy,
            force_same_tab_navigation=force_same_tab_navigation,
            auto_follow_new_page=auto_follow_new_page,
            force_chrome_select_rendering=force_chrome_select_rendering,
        )
        await instance._install_force_chrome_select_rendering()
        return instance

    async def _install_force_chrome_select_rendering(self) -> None:
        try:
            await apply_force_chrome_select_rendering(
                self.page, enabled=self._force_chrome_select_rendering
            )
        except Exception as e:
            logger.debug(f"Failed to add base-select style: {e}")

    async def _on_popup(self, popup: Any) -> None:
        """Keep target=_blank navigation in the current tab (upstream
        forceClosePopup)."""
        try:
            url = popup.url
        except Exception:
            url = ""
        logger.info(f"Popup opened: {url}")
        try:
            if not popup.is_closed():
                await popup.close()
        except Exception as e:
            logger.debug(f"Failed to close popup {url}: {e}")
        if url and not self._initial_page.is_closed():
            try:
                await self._initial_page.goto(
                    url, wait_until="domcontentloaded", timeout=10000
                )
            except Exception as e:
                logger.debug(f"Failed to open popup url {url} in current tab: {e}")

    async def _on_new_page(self, page: Any) -> None:
        """Follow the newest page (upstream autoFollowNewPage)."""
        self.page = page

    async def _judge_order_sensitive(
        self, options: dict[str, Any] | None = None
    ) -> bool:
        return await judge_order_sensitive(options)

    @property
    def interface_type(self) -> InterfaceType:
        """Get interface type"""
        return InterfaceType.WEB

    async def get_context(self) -> UIContext:
        """Get current UI context"""
        try:
            # Take screenshot
            screenshot_base64 = await self._take_screenshot()

            # Get page size
            size = await self._get_page_size()

            # Extract DOM elements
            elements = await self._extract_elements()

            # Build UI tree
            tree = await self._build_ui_tree()

            return UIContext(
                screenshot_base64=screenshot_base64,
                size=size,
                content=elements,
                tree=tree,
            )

        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            raise

    async def action_space(self) -> list[str]:
        """Get available actions"""
        return [
            "tap",
            "click",
            "double_click",
            "right_click",
            "input",
            "type",
            "fill",
            "clear",
            "scroll",
            "scroll_up",
            "scroll_down",
            "scroll_left",
            "scroll_right",
            "hover",
            "drag",
            "key_press",
            "navigate",
            "reload",
            "go_back",
            "go_forward",
        ]

    async def register_file_chooser_listener(
        self, handler: Any
    ) -> FileChooserRegistration:
        """Accept files when the page opens a native file chooser dialog
        (upstream PlaywrightWebPage.registerFileChooserListener)."""
        captured: dict[str, BaseException | None] = {"error": None}

        async def _on_file_chooser(chooser: Any) -> None:
            async def accept(files: list[str]) -> None:
                await chooser.set_files(list(files))

            try:
                await handler(FileChooserHandler(accept=accept))
            except BaseException as e:  # noqa: BLE001 - surfaced via get_error
                captured["error"] = e

        self.page.on("filechooser", _on_file_chooser)

        def dispose() -> None:
            try:
                self.page.remove_listener("filechooser", _on_file_chooser)
            except Exception as e:
                logger.warning(f"Error removing file chooser listener: {e}")

        return FileChooserRegistration(
            dispose=dispose, get_error=lambda: captured["error"]
        )

    async def navigate_to(self, url: str) -> None:
        """Navigate to URL"""
        try:
            await self.page.goto(url, wait_until="networkidle")
        except Exception as e:
            logger.error(f"Failed to navigate to {url}: {e}")
            raise

    async def reload(self) -> None:
        """Reload the current page."""
        await self.page.reload()

    async def go_back(self) -> None:
        """Navigate back in browser history."""
        await self.page.go_back()

    async def go_forward(self) -> None:
        """Navigate forward in browser history."""
        await self.page.go_forward()

    async def execute_script(self, script: str, *args) -> Any:
        """Evaluate JavaScript in the page and return its value."""
        if args:
            argument = args[0] if len(args) == 1 else list(args)
            return await self.page.evaluate(script, argument)
        return await self.page.evaluate(script)

    async def wait_for_element(self, selector: str, timeout: float = 10000) -> None:
        """Wait for element to be present"""
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
        except Exception as error:
            raise TimeoutError(f"Element not found: {selector}") from error

    async def evaluate_script(self, script: str, *args) -> Any:
        """Evaluate JavaScript"""
        return await self.page.evaluate(script, *args)

    async def close(self) -> None:
        """Close the browser and the Playwright driver started by create()."""
        if self._popup_handler is not None:
            try:
                await self._initial_page.remove_listener("popup", self._popup_handler)
            except Exception:
                pass
            self._popup_handler = None
        if self._new_page_handler is not None:
            try:
                await self.context.remove_listener("page", self._new_page_handler)
            except Exception:
                pass
            self._new_page_handler = None
        try:
            await self.context.close()
            await self.browser.close()
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

    async def _take_screenshot(self) -> str:
        """Take screenshot and return base64 string"""
        try:
            return await take_screenshot_base64(self.page)
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise

    async def screenshot_base64(self) -> str:
        """Capture the current page as base64 (interface contract)."""
        return await self._take_screenshot()

    async def _get_page_size(self) -> Size:
        """Get page viewport size"""
        try:
            return await get_page_size(self.page)
        except Exception as e:
            logger.error(f"Failed to get page size: {e}")
            return Size(width=1920, height=1080)

    async def _extract_elements(self) -> list[PlaywrightElement]:
        """Extract all visible elements from page"""
        try:
            # Use JavaScript to extract element information
            element_data = await self.page.evaluate("""
                () => {
                    const elements = [];
                    const allElements = document.querySelectorAll('*');

                    allElements.forEach((el, index) => {
                        const rect = el.getBoundingClientRect();

                        // Skip elements that are not visible
                        if (rect.width === 0 || rect.height === 0 ||
                            rect.top < 0 || rect.left < 0 ||
                            getComputedStyle(el).visibility === 'hidden' ||
                            getComputedStyle(el).display === 'none') {
                            return;
                        }

                        // Generate a selector for this element
                        const selector = generateSelector(el);

                        elements.push({
                            id: `element_${index}`,
                            selector: selector,
                            tagName: el.tagName.toLowerCase(),
                            content: el.textContent?.trim() || el.getAttribute('alt') || el.getAttribute('title') || '',
                            rect: {
                                left: rect.left,
                                top: rect.top,
                                width: rect.width,
                                height: rect.height
                            },
                            center: [rect.left + rect.width / 2, rect.top + rect.height / 2],
                            attributes: {
                                id: el.id,
                                className: el.className,
                                type: el.type,
                                name: el.name,
                                href: el.href,
                                src: el.src,
                                value: el.value,
                                placeholder: el.placeholder
                            }
                        });
                    });

                    function generateSelector(element) {
                        if (element.id) {
                            return `#${element.id}`;
                        }

                        let path = element.tagName.toLowerCase();
                        let parent = element.parentElement;

                        while (parent && parent !== document.body) {
                            const siblings = Array.from(parent.children);
                            const index = siblings.indexOf(element) + 1;
                            path = `${parent.tagName.toLowerCase()}:nth-child(${index}) > ${path}`;
                            element = parent;
                            parent = element.parentElement;
                        }

                        return path;
                    }

                    return elements;
                }
            """)

            elements = []
            for data in element_data:
                rect_data = data["rect"]
                rect = Rect(
                    left=rect_data["left"],
                    top=rect_data["top"],
                    width=rect_data["width"],
                    height=rect_data["height"],
                )

                # Determine node type
                tag_name = data["tagName"]
                node_type = self._get_node_type(tag_name, data["attributes"])

                element = PlaywrightElement(
                    page=self.page,
                    selector=data["selector"],
                    id=data["id"],
                    content=data["content"],
                    rect=rect,
                    center=tuple(data["center"]),
                    node_type=node_type,
                    attributes=data["attributes"],
                    is_visible=True,
                )

                elements.append(element)

            return elements

        except Exception as e:
            logger.error(f"Failed to extract elements: {e}")
            return []

    def _get_node_type(self, tag_name: str, attributes: dict[str, Any]) -> NodeType:
        """Determine node type from tag name and attributes"""
        if tag_name in ["input", "textarea"]:
            input_type = attributes.get("type", "").lower()
            if input_type in ["text", "password", "email", "search", "url", "tel"]:
                return NodeType.INPUT
            elif input_type in ["button", "submit", "reset"]:
                return NodeType.BUTTON
        elif tag_name in ["button"]:
            return NodeType.BUTTON
        elif tag_name in ["a"]:
            return NodeType.LINK
        elif tag_name in ["img"]:
            return NodeType.IMAGE
        elif tag_name in [
            "div",
            "span",
            "section",
            "article",
            "header",
            "footer",
            "nav",
        ]:
            return NodeType.CONTAINER
        elif tag_name in ["p", "h1", "h2", "h3", "h4", "h5", "h6", "label", "td", "th"]:
            return NodeType.TEXT
        else:
            return NodeType.OTHER

    async def _build_ui_tree(self) -> UITree:
        """Build UI tree structure"""
        try:
            # Simplified tree building - just create a root container
            # In a full implementation, we would parse the actual DOM tree
            root_node = UINode(
                id="root",
                content="",
                rect=Rect(left=0, top=0, width=1920, height=1080),
                center=(960, 540),
                node_type=NodeType.CONTAINER,
                attributes={},
                is_visible=True,
                children=[],
            )

            return UITree(node=root_node, children=[])

        except Exception as e:
            logger.error(f"Failed to build UI tree: {e}")
            # Return minimal tree
            root_node = UINode(
                id="root",
                content="",
                rect=Rect(left=0, top=0, width=1920, height=1080),
                center=(960, 540),
                node_type=NodeType.CONTAINER,
                attributes={},
                is_visible=True,
                children=[],
            )
            return UITree(node=root_node, children=[])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Historical Python name for the upstream Playwright ``WebPage`` class.
PlaywrightWebPage = WebPage

__all__ = ["PlaywrightWebPage", "WebPage"]
