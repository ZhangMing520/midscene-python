"""
Playwright integration for Midscene
"""

import asyncio
import base64
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from loguru import logger

from ..core.types import (
    AbstractInterface, InterfaceType, UIContext, BaseElement, UINode, UITree,
    Size, Rect, NodeType
)
from ..core.ai_model.workflows.order_sensitive import resolve_order_sensitive

# Locate-cache feature extraction, mirroring upstream getElementXpath:
# leaf elements use their normalized text, ancestors use sibling indexes.
_XPATHS_AT_POINT_JS = r"""([x, y, isOrderSensitive]) => {

  const SEP = '|>>|';
  const MAX_DEPTH = 10;
  const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
  const normalizeText = (text) => (text || '').replace(/\s+/g, ' ').trim();

  const indexPath = (node) => {
    let index = 1;
    let previous = node.previousElementSibling;
    while (previous) {
      if (previous.nodeName.toLowerCase() === node.nodeName.toLowerCase()) {
        index += 1;
      }
      previous = previous.previousElementSibling;
    }
    return index;
  };

  const buildXpath = (node, isLeaf) => {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return '';
    const tagName = node.nodeName.toLowerCase();
    // html/body have a single canonical path, as in upstream getElementXpath.
    if (tagName === 'html') return '/html';
    if (tagName === 'body') return '/html/body';
    const parentPath = buildXpath(node.parentNode, false);
    const selector = node.namespaceURI === SVG_NAMESPACE
      ? `*[name()="${tagName}"]`
      : tagName;
    const prefix = parentPath ? `${parentPath}/` : '/';
    const text = normalizeText(node.textContent);
    if (isLeaf && !isOrderSensitive && text && !text.includes('"')) {
      return `${prefix}${selector}[normalize-space()="${text}"]`;
    }
    return `${prefix}${selector}[${indexPath(node)}]`;
  };

  let currentWindow = window;
  let currentDocument = document;
  let left = x;
  let top = y;
  let xpathPrefix = '';

  for (let depth = 0; depth < MAX_DEPTH; depth++) {
    const element = currentDocument.elementFromPoint(left, top);
    if (!element) return [];
    // Shadow DOM nodes have no document-level xpath; caching the host would
    // replay onto the wrong target, so skip caching entirely.
    if (element.getRootNode() !== currentDocument || element.shadowRoot) return [];

    const tagName = element.tagName.toLowerCase();
    if (tagName === 'iframe' || tagName === 'frame') {
      const contentDocument = element.contentDocument;
      const contentWindow = element.contentWindow;
      if (contentDocument && contentWindow) {
        const frameRect = element.getBoundingClientRect();
        const style = currentWindow.getComputedStyle(element);
        const zoom = Number.parseFloat(style.zoom || '1') || 1;
        const paddingLeft = Number.parseFloat(style.paddingLeft) || 0;
        const paddingTop = Number.parseFloat(style.paddingTop) || 0;
        left = (left - frameRect.left - element.clientLeft - paddingLeft) / zoom;
        top = (top - frameRect.top - element.clientTop - paddingTop) / zoom;
        xpathPrefix += buildXpath(element, false) + SEP;
        currentWindow = contentWindow;
        currentDocument = contentDocument;
        continue;
      }
      // Cross-origin frame: its document is unreachable, and caching the
      // iframe host would replay onto the frame center instead of the target.
      return [];
    }

    return [xpathPrefix + buildXpath(element, true)];
  }
  return [];
}"""

_RECT_FOR_XPATH_JS = """(xpath) => {
  const SEP = '|>>|';
  const parts = String(xpath || '')
    .split(SEP)
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return null;

  let currentDocument = document;
  let node = null;
  for (let index = 0; index < parts.length; index++) {
    let result;
    try {
      result = currentDocument.evaluate(
        parts[index], currentDocument, null,
        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
      );
    } catch (error) {
      return null;
    }
    // An ambiguous path must not silently resolve to the first match.
    if (result.snapshotLength !== 1) return null;
    node = result.snapshotItem(0);
    if (index === parts.length - 1) break;
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
    const tagName = node.tagName.toLowerCase();
    if (tagName !== 'iframe' && tagName !== 'frame') return null;
    const nextDocument = node.contentDocument;
    if (!nextDocument) return null;
    currentDocument = nextDocument;
  }
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;

  const rect = node.getBoundingClientRect();
  let left = rect.left;
  let top = rect.top;
  let frameDocument = node.ownerDocument;
  while (frameDocument && frameDocument !== document) {
    const frame = frameDocument.defaultView && frameDocument.defaultView.frameElement;
    if (!frame) break;
    const frameRect = frame.getBoundingClientRect();
    let borderLeft = 0;
    let borderTop = 0;
    let zoom = 1;
    try {
      const style = frame.ownerDocument.defaultView.getComputedStyle(frame);
      borderLeft = Number.parseFloat(style.borderLeftWidth) || 0;
      borderTop = Number.parseFloat(style.borderTopWidth) || 0;
      zoom = Number.parseFloat(style.zoom || '1') || 1;
    } catch (error) {
      // cross-document style access can fail; use the defaults
    }
    left = left / zoom + frameRect.left + borderLeft;
    top = top / zoom + frameRect.top + borderTop;
    frameDocument = frame.ownerDocument;
  }
  return {
    left: left,
    top: top,
    width: rect.width,
    height: rect.height,
  };
}"""


class PlaywrightElement(BaseElement):
    """Playwright element wrapper"""
    
    def __init__(self, page: Page, selector: str, **kwargs):
        self._page = page
        self._selector = selector
        super().__init__(**kwargs)
    
    async def tap(self) -> None:
        """Click this element"""
        try:
            await self._page.click(self._selector)
        except Exception as e:
            logger.error(f"Failed to click element: {e}")
            raise
    
    async def input_text(self, text: str) -> None:
        """Input text to this element"""
        try:
            await self._page.fill(self._selector, text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise


class PlaywrightWebPage(AbstractInterface):
    """Playwright page interface"""
    
    def __init__(
        self,
        page: Page,
        context: BrowserContext,
        browser: Browser,
        playwright: Optional[Any] = None,
    ):
        """Initialize with Playwright page
        
        Args:
            page: Playwright page instance
            context: Browser context
            browser: Browser instance
            playwright: Playwright instance started by create(), stopped on close
        """
        self.page = page
        self.context = context
        self.browser = browser
        self._playwright = playwright
    
    @classmethod
    async def create(
        cls,
        headless: bool = False,
        viewport_size: tuple[int, int] = (1920, 1080),
        user_data_dir: Optional[str] = None,
        user_agent: Optional[str] = None,
        **browser_options
    ) -> 'PlaywrightWebPage':
        """Create new Playwright page instance
        
        Args:
            headless: Run in headless mode
            viewport_size: Browser viewport size
            user_data_dir: Browser user data directory
            user_agent: Browser User-Agent string
            **browser_options: Additional browser launch options (e.g. args)
            
        Returns:
            PlaywrightWebPage instance
        """
        playwright = await async_playwright().start()
        
        launch_options = {
            "headless": headless,
            **browser_options
        }
        
        if user_data_dir:
            launch_options["user_data_dir"] = user_data_dir
        
        browser = await playwright.chromium.launch(**launch_options)
        
        context = await browser.new_context(
            viewport={"width": viewport_size[0], "height": viewport_size[1]},
            user_agent=user_agent,
        )
        
        page = await context.new_page()
        
        return cls(page, context, browser, playwright)
    
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
                tree=tree
            )
            
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            raise
    
    async def action_space(self) -> List[str]:
        """Get available actions"""
        return [
            "tap", "click", "double_click", "right_click",
            "input", "type", "fill", "clear",
            "scroll", "scroll_up", "scroll_down", "scroll_left", "scroll_right",
            "hover", "drag", "key_press", "navigate", "reload",
            "go_back", "go_forward"
        ]
    
    async def tap(self, x: float, y: float) -> None:
        """Tap at coordinates"""
        try:
            await self.page.mouse.click(x, y)
        except Exception as e:
            logger.error(f"Failed to tap at ({x}, {y}): {e}")
            raise

    async def right_click(self, x: float, y: float) -> None:
        try:
            await self.page.mouse.click(x, y, button="right")
        except Exception as e:
            logger.error(f"Failed to right click at ({x}, {y}): {e}")
            raise

    async def middle_click(self, x: float, y: float) -> None:
        try:
            await self.page.mouse.click(x, y, button="middle")
        except Exception as e:
            logger.error(f"Failed to middle click at ({x}, {y}): {e}")
            raise

    async def double_click(self, x: float, y: float) -> None:
        try:
            await self.page.mouse.dblclick(x, y)
        except Exception as e:
            logger.error(f"Failed to double click at ({x}, {y}): {e}")
            raise

    async def hover(self, x: float, y: float) -> None:
        try:
            await self.page.mouse.move(x, y)
        except Exception as e:
            logger.error(f"Failed to hover at ({x}, {y}): {e}")
            raise

    async def pinch(
        self,
        direction: str,
        point: Optional[List[float]] = None,
        distance: Optional[int] = None,
        duration: Optional[int] = None,
    ) -> None:
        """Two-finger pinch via CDP touch events (upstream web Pinch).

        direction 'out' zooms out (fingers move together), 'in' zooms in
        (fingers move apart).
        """
        if direction not in ("in", "out"):
            raise ValueError('pinch direction must be "in" or "out"')
        viewport = self.page.viewport_size or {"width": 1280, "height": 720}
        cx = float(point[0]) if point else viewport["width"] / 2
        cy = float(point[1]) if point else viewport["height"] / 2
        spread = float(distance if distance is not None else 100)
        duration_s = (duration if duration is not None else 600) / 1000
        steps = 12
        gap_start = spread / 2
        gap_end = 10.0 if direction == "out" else spread / 2 + spread / 2
        if direction == "in":
            gap_start, gap_end = 10.0, spread / 2 + spread / 2

        cdp = await self.context.new_cdp_session(self.page)

        async def touch(token: str, phase: str, x: float, y: float) -> None:
            await cdp.send(
                "Input.dispatchTouchEvent",
                {
                    "type": phase,
                    "touchPoints": [
                        {"x": x, "y": y, "id": 0},
                        {"x": 2 * cx - x, "y": 2 * cy - y, "id": 1},
                    ]
                    if phase != "touchEnd"
                    else [],
                },
            )

        try:
            await touch("start", "touchStart", cx - gap_start, cy - gap_start)
            for step in range(1, steps + 1):
                t = step / steps
                gap = gap_start + (gap_end - gap_start) * t
                await asyncio.sleep(duration_s / steps)
                await touch("move", "touchMove", cx - gap, cy - gap)
            await touch("end", "touchEnd", cx - gap_end, cy - gap_end)
        finally:
            await cdp.detach()

    async def drag_and_drop(self, from_point, to_point) -> None:
        """Drag from one point to another (upstream page.mouse.drag)."""
        try:
            from_x, from_y = from_point
            to_x, to_y = to_point
            await self.page.mouse.move(from_x, from_y)
            await self.page.mouse.down()
            await self.page.mouse.move(to_x, to_y, steps=10)
            await self.page.mouse.up()
        except Exception as e:
            logger.error(f"Failed to drag from {from_point} to {to_point}: {e}")
            raise

    async def cache_feature_for_point(
        self, center: List[float], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build the xpath-based locate-cache feature for a point."""
        order_sensitive = await resolve_order_sensitive(options)
        try:
            xpaths = await self.page.evaluate(
                _XPATHS_AT_POINT_JS,
                [float(center[0]), float(center[1]), order_sensitive],
            )
        except Exception as e:
            logger.warning(f"Failed to build cache feature for {center}: {e}")
            xpaths = []
        return {
            "xpaths": [
                xpath for xpath in (xpaths or []) if isinstance(xpath, str) and xpath
            ]
        }

    async def rect_matches_cache_feature(
        self, feature: Dict[str, Any]
    ) -> Optional[Rect]:
        """Resolve cached xpaths back to the first matching element rect."""
        xpaths = (feature or {}).get("xpaths") or []
        for xpath in xpaths:
            if not isinstance(xpath, str) or not xpath:
                continue
            try:
                rect = await self.page.evaluate(_RECT_FOR_XPATH_JS, xpath)
            except Exception as e:
                logger.debug(f"Failed to evaluate cached xpath {xpath}: {e}")
                continue
            if rect:
                return Rect(**rect)
        return None

    async def keyboard_press(self, key: str) -> None:
        try:
            await self.page.keyboard.press(key)
        except Exception as e:
            logger.error(f"Failed to press key {key}: {e}")
            raise

    async def clear_input(self) -> None:
        try:
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Delete")
        except Exception as e:
            logger.error(f"Failed to clear input: {e}")
            raise

    async def replace_input(self, text: str) -> None:
        try:
            await self.page.keyboard.press("Control+A")
            await self.page.keyboard.type(text)
        except Exception as e:
            logger.error(f"Failed to replace input: {e}")
            raise

    async def input_text(self, text: str) -> None:
        """Input text to focused element"""
        try:
            await self.page.keyboard.type(text)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        """Scroll in direction"""
        try:
            scroll_type = kwargs.get("scroll_type") or "singleAction"
            point = kwargs.get("point")
            if scroll_type.startswith("scrollTo"):
                target = scroll_type.replace("scrollTo", "").lower()
                if point and target in ("bottom", "top", "right", "left"):
                    await self.page.evaluate(
                        """([x, y, mode]) => {
                          const el = document.elementFromPoint(x, y);
                          let node = el;
                          while (node && node !== document.body &&
                                 node !== document.documentElement &&
                                 node.scrollHeight <= node.clientHeight &&
                                 node.scrollWidth <= node.clientWidth) {
                            node = node.parentElement;
                          }
                          const target = (node && node !== document.body &&
                                          node !== document.documentElement)
                            ? node
                            : (document.scrollingElement || document.documentElement);
                          if (mode === 'bottom') target.scrollTo({top: target.scrollHeight, behavior: 'instant'});
                          else if (mode === 'top') target.scrollTo({top: 0, behavior: 'instant'});
                          else if (mode === 'right') target.scrollTo({left: target.scrollWidth, behavior: 'instant'});
                          else if (mode === 'left') target.scrollTo({left: 0, behavior: 'instant'});
                        }""",
                        [point[0], point[1], target],
                    )
                    return
                if target == "bottom":
                    await self.page.evaluate(
                        "window.scrollTo({left: 0, top: document.body.scrollHeight, behavior: 'instant'})"
                    )
                    return
                if target == "right":
                    await self.page.evaluate(
                        "window.scrollTo({left: document.body.scrollWidth, top: 0, behavior: 'instant'})"
                    )
                    return
                if target in ("top", "left"):
                    await self.page.evaluate(
                        "window.scrollTo({left: 0, top: 0, behavior: 'instant'})"
                    )
                    return

            distance = distance or 500

            if point:
                await self.page.mouse.move(point[0], point[1])

            if direction == "down":
                await self.page.mouse.wheel(0, distance)
            elif direction == "up":
                await self.page.mouse.wheel(0, -distance)
            elif direction == "right":
                await self.page.mouse.wheel(distance, 0)
            elif direction == "left":
                await self.page.mouse.wheel(-distance, 0)
            else:
                raise ValueError(f"Invalid scroll direction: {direction}")
            # Wheel scrolling settles asynchronously in Chromium.
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Failed to scroll {direction}: {e}")
            raise
    
    async def navigate_to(self, url: str) -> None:
        """Navigate to URL"""
        try:
            await self.page.goto(url, wait_until="networkidle")
        except Exception as e:
            logger.error(f"Failed to navigate to {url}: {e}")
            raise
    
    async def wait_for_element(
        self, 
        selector: str, 
        timeout: float = 10000
    ) -> None:
        """Wait for element to be present"""
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
        except Exception:
            raise TimeoutError(f"Element not found: {selector}")
    
    async def evaluate_script(self, script: str, *args) -> Any:
        """Evaluate JavaScript"""
        return await self.page.evaluate(script, *args)
    
    async def close(self) -> None:
        """Close the browser and the Playwright driver started by create()."""
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
            # Take screenshot as bytes
            screenshot_bytes = await self.page.screenshot(type="png")
            
            # Convert to base64
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            return screenshot_base64
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise
    
    async def _get_page_size(self) -> Size:
        """Get page viewport size"""
        try:
            viewport_size = await self.page.evaluate("""
                () => ({
                    width: window.innerWidth,
                    height: window.innerHeight
                })
            """)
            
            return Size(
                width=viewport_size['width'],
                height=viewport_size['height']
            )
            
        except Exception as e:
            logger.error(f"Failed to get page size: {e}")
            return Size(width=1920, height=1080)
    
    async def _extract_elements(self) -> List[PlaywrightElement]:
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
                rect_data = data['rect']
                rect = Rect(
                    left=rect_data['left'],
                    top=rect_data['top'],
                    width=rect_data['width'],
                    height=rect_data['height']
                )
                
                # Determine node type
                tag_name = data['tagName']
                node_type = self._get_node_type(tag_name, data['attributes'])
                
                element = PlaywrightElement(
                    page=self.page,
                    selector=data['selector'],
                    id=data['id'],
                    content=data['content'],
                    rect=rect,
                    center=tuple(data['center']),
                    node_type=node_type,
                    attributes=data['attributes'],
                    is_visible=True
                )
                
                elements.append(element)
            
            return elements
            
        except Exception as e:
            logger.error(f"Failed to extract elements: {e}")
            return []
    
    def _get_node_type(self, tag_name: str, attributes: Dict[str, Any]) -> NodeType:
        """Determine node type from tag name and attributes"""
        if tag_name in ['input', 'textarea']:
            input_type = attributes.get('type', '').lower()
            if input_type in ['text', 'password', 'email', 'search', 'url', 'tel']:
                return NodeType.INPUT
            elif input_type in ['button', 'submit', 'reset']:
                return NodeType.BUTTON
        elif tag_name in ['button']:
            return NodeType.BUTTON
        elif tag_name in ['a']:
            return NodeType.LINK
        elif tag_name in ['img']:
            return NodeType.IMAGE
        elif tag_name in ['div', 'span', 'section', 'article', 'header', 'footer', 'nav']:
            return NodeType.CONTAINER
        elif tag_name in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label', 'td', 'th']:
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
                children=[]
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
                children=[]
            )
            return UITree(node=root_node, children=[])
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()