"""Browser page actions (upstream common/browser-page-actions.ts).

The first half mirrors upstream: ``create_browser_agent_page_actions`` builds
the ``ListBrowserPages`` / ``GetBrowserPageInfo`` / ``SetActivePage`` device
actions.  The second half keeps the driver-agnostic page action helpers that
``PlaywrightWebPage`` inherits; those only depend on the small subset of the
Playwright ``Page`` API that every web page interface exposes.
"""

import asyncio
import math
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.types import Rect
from midscene.web_integration.common.cache_helper import (
    judge_order_sensitive,
    sanitize_xpaths,
)
from midscene.web_integration.common.input_scripts import SELECT_ALL_INPUT_SCRIPT

INPUT_STRATEGIES = ("legacy", "sequential", "bulk")

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


def _resolve_text_input_options(
    input_strategy: Optional[str], keyboard_type_delay: Optional[float]
) -> "tuple[str, Optional[float]]":
    """Validate the text typing options (upstream resolveInputStrategy)."""
    if keyboard_type_delay is not None:
        delay: Optional[float] = float(keyboard_type_delay)
        if not math.isfinite(delay) or delay < 0:
            raise ValueError(
                "keyboardTypeDelay must be a finite non-negative number"
            )
    else:
        delay = None
    strategy = "legacy" if input_strategy is None else input_strategy
    if strategy not in INPUT_STRATEGIES:
        raise ValueError(
            "inputStrategy must be one of: "
            f"{', '.join(INPUT_STRATEGIES)}; received {strategy}"
        )
    if strategy == "bulk" and delay is not None and delay > 0:
        raise ValueError(
            'inputStrategy "bulk" requires keyboardTypeDelay to be omitted or '
            'set to 0; use inputStrategy "sequential" for delayed input'
        )
    return strategy, delay


class BrowserPageActionsMixin:
    """Mouse/keyboard/scroll primitives shared by browser page interfaces."""

    # These attributes are provided by the concrete page class.
    page: Any
    context: Any
    keyboard_type_delay: Optional[float]
    input_strategy: Optional[str]

    async def _judge_order_sensitive(
        self, options: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Hook so callers can override the order-sensitive judgement."""
        return await judge_order_sensitive(options)

    async def tap(self, x: float, y: float) -> None:
        """Tap at coordinates."""
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
        center: List[float],
        start_distance: float,
        end_distance: float,
        duration: Optional[int] = None,
    ) -> None:
        """Two-finger pinch via CDP touch events (upstream web pinch).

        The fingers are vertical around `center`; `start_distance` and
        `end_distance` are the gaps between them at press and release.
        """
        center_x = float(center[0])
        center_y = float(center[1])
        duration_s = (duration if duration is not None else 500) / 1000
        steps = 30
        half_start = start_distance / 2
        half_end = end_distance / 2

        cdp = await self.context.new_cdp_session(self.page)

        async def dispatch(phase: str, half: float) -> None:
            points = (
                []
                if phase == "touchEnd"
                else [
                    {"x": round(center_x), "y": round(center_y - half), "id": 0},
                    {"x": round(center_x), "y": round(center_y + half), "id": 1},
                ]
            )
            await cdp.send(
                "Input.dispatchTouchEvent",
                {"type": phase, "touchPoints": points, "modifiers": 0},
            )

        try:
            await dispatch("touchStart", half_start)
            for step in range(1, steps + 1):
                progress = step / steps
                half = half_start + (half_end - half_start) * progress
                await dispatch("touchMove", half)
                await asyncio.sleep(duration_s / steps)
            await dispatch("touchEnd", half_end)
        finally:
            await cdp.detach()

    async def swipe(
        self,
        direction: str,
        distance: Optional[int] = None,
        duration: Optional[int] = None,
    ) -> None:
        """Mouse swipe that honors an explicit duration (upstream base-page swipe).

        `up` drags the pointer towards the top, matching the finger-movement
        convention used by the Swipe action. Durations are never capped: a slow
        gesture is not a long press.
        """
        if direction not in ("up", "down", "left", "right"):
            raise ValueError(f"Invalid swipe direction: {direction}")
        viewport = self.page.viewport_size or {"width": 1280, "height": 720}
        width, height = viewport["width"], viewport["height"]
        span = int(min(distance or min(width, height) // 2, width, height))
        offsets = {
            "up": (0, -span),
            "down": (0, span),
            "left": (-span, 0),
            "right": (span, 0),
        }
        dx, dy = offsets[direction]
        start_x = min(max(width / 2 - dx / 2, 1), width - 1)
        start_y = min(max(height / 2 - dy / 2, 1), height - 1)
        end_x = min(max(start_x + dx, 1), width - 1)
        end_y = min(max(start_y + dy, 1), height - 1)
        await self._mouse_swipe(start_x, start_y, end_x, end_y, duration)

    async def swipe_points(
        self,
        start: List[float],
        end: List[float],
        duration: Optional[int] = None,
    ) -> None:
        """Endpoint pointer swipe between two viewport points (upstream swipe)."""
        await self._mouse_swipe(start[0], start[1], end[0], end[1], duration)

    async def size(self) -> Dict[str, int]:
        """Viewport size in logical pixels (upstream size())."""
        viewport = self.page.viewport_size or {"width": 1280, "height": 720}
        return {"width": int(viewport["width"]), "height": int(viewport["height"])}

    async def _mouse_swipe(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        duration: Optional[int] = None,
    ) -> None:
        """Press, move in 30 steps and release; the pointer is always released."""
        duration_ms = max(int(duration or 100), 150)
        steps = 30
        await self.page.mouse.move(start_x, start_y)
        await self.page.mouse.down()
        completed = False
        try:
            for step in range(1, steps + 1):
                ratio = step / steps
                await self.page.mouse.move(
                    start_x + (end_x - start_x) * ratio,
                    start_y + (end_y - start_y) * ratio,
                )
                await asyncio.sleep(duration_ms / steps / 1000)
            completed = True
        finally:
            if completed:
                await self.page.mouse.up()
            else:
                try:
                    await self.page.mouse.up()
                except Exception:
                    pass

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
        order_sensitive = await self._judge_order_sensitive(options)
        try:
            xpaths = await self.page.evaluate(
                _XPATHS_AT_POINT_JS,
                [float(center[0]), float(center[1]), order_sensitive],
            )
        except Exception as e:
            logger.warning(f"Failed to build cache feature for {center}: {e}")
            xpaths = []
        return {"xpaths": sanitize_xpaths(xpaths)}

    async def rect_matches_cache_feature(
        self, feature: Dict[str, Any]
    ) -> Rect:
        """Resolve cached xpaths back to the first matching element rect."""
        xpaths = sanitize_xpaths((feature or {}).get("xpaths"))
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
        raise RuntimeError(
            "No matching element rect found for the provided cache feature "
            f"(tried {len(xpaths)} xpath(s): {', '.join(xpaths)})"
        )

    async def keyboard_press(self, key: str) -> None:
        try:
            await self.page.keyboard.press(key)
        except Exception as e:
            logger.error(f"Failed to press key {key}: {e}")
            raise

    async def clear_input(self) -> None:
        try:
            selected = await self.page.evaluate(SELECT_ALL_INPUT_SCRIPT)
            if not selected:
                await self.page.keyboard.press("Control+A")
            await self.page.keyboard.press("Delete")
        except Exception as e:
            logger.error(f"Failed to clear input: {e}")
            raise

    def _text_input_options(
        self,
        keyboard_type_delay: Optional[float],
        input_strategy: Optional[str],
    ) -> "tuple[str, Optional[float]]":
        delay = (
            self.keyboard_type_delay
            if keyboard_type_delay is None
            else keyboard_type_delay
        )
        strategy = self.input_strategy if input_strategy is None else input_strategy
        return _resolve_text_input_options(strategy, delay)

    async def _type_text(
        self, text: str, strategy: str, delay: Optional[float]
    ) -> None:
        if strategy == "bulk":
            await self.page.keyboard.insert_text(text)
            return
        if strategy == "sequential":
            characters = list(text)
            for index, character in enumerate(characters):
                await self.page.keyboard.type(character, delay=0)
                if delay and delay > 0 and index < len(characters) - 1:
                    await asyncio.sleep(delay / 1000)
            return
        options = {} if delay is None else {"delay": delay}
        await self.page.keyboard.type(text, **options)

    async def replace_input(
        self,
        text: str,
        keyboard_type_delay: Optional[float] = None,
        input_strategy: Optional[str] = None,
    ) -> None:
        try:
            strategy, delay = self._text_input_options(
                keyboard_type_delay, input_strategy
            )
            await self.page.keyboard.press("Control+A")
            await self._type_text(text, strategy, delay)
        except Exception as e:
            logger.error(f"Failed to replace input: {e}")
            raise

    async def input_text(
        self,
        text: str,
        keyboard_type_delay: Optional[float] = None,
        input_strategy: Optional[str] = None,
    ) -> None:
        """Input text to focused element."""
        try:
            strategy, delay = self._text_input_options(
                keyboard_type_delay, input_strategy
            )
            await self._type_text(text, strategy, delay)
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            raise

    async def scroll(
        self, direction: str, distance: Optional[int] = None, **kwargs
    ) -> None:
        """Scroll in direction."""
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

            horizontal = direction in ("left", "right")
            viewport = self.page.viewport_size or {"width": 1280, "height": 720}
            if point:
                await self.page.mouse.move(point[0], point[1])
            else:
                # An unmoved pointer keeps the wheel event on whatever the
                # browser last hovered; center it over the page first.
                await self.page.mouse.move(
                    viewport["width"] // 2, viewport["height"] // 2
                )

            if distance is None:
                distance = (
                    viewport["width"] if horizontal else viewport["height"]
                ) * 0.7

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

    async def cursor_move(self, direction: str, times: int = 1) -> None:
        """Move the caret inside the focused field (upstream web cursorMove)."""
        if direction not in ("left", "right"):
            raise ValueError(f"Invalid cursor direction: {direction}")
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(max(1, int(times))):
            await self.page.keyboard.press(arrow_key)
            await asyncio.sleep(0.1)


PAGE_LIST_SIZE = 8
MAX_LIST_TITLE_LENGTH = 120
MAX_LIST_URL_LENGTH = 512


def _normalize_feedback_value(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truncate_feedback_value(value: str, max_length: int) -> str:
    """Truncate like upstream truncateFeedbackValue (middle ellipsis)."""
    if max_length <= 0:
        return ""
    if len(value) <= max_length:
        return value
    if max_length <= 2:
        return f"{value[: max_length - 1]}…"
    head_length = math.ceil(((max_length - 1) * 2) / 3)
    tail_length = max_length - head_length - 1
    return f"{value[:head_length]}…{value[-tail_length:]}"


def _build_planning_feedback(
    summaries: List[Dict[str, Any]],
    total: int,
    offset: int,
    active_index: Optional[int],
) -> str:
    if total == 0:
        return "ListBrowserPages: no open pages."

    next_offset = offset + len(summaries)
    continuation = (
        f" Next: ListBrowserPages({{offset:{next_offset}}})."
        if next_offset < total
        else ""
    )
    header = (
        f"ListBrowserPages {offset}-{next_offset - 1} of {total}; "
        f"active {active_index if active_index is not None else 'none'} "
        f"(0-based). Use SetActivePage.{continuation}\n"
    )
    if not summaries:
        return header.rstrip()

    lines = []
    for summary in summaries:
        prefix = f"{'*' if summary.get('active') else ' '}{summary.get('index')}|"
        title = _truncate_feedback_value(
            _normalize_feedback_value(summary.get("title")), MAX_LIST_TITLE_LENGTH
        )
        url = _truncate_feedback_value(
            _normalize_feedback_value(summary.get("url")), MAX_LIST_URL_LENGTH
        )
        lines.append(f"{prefix}{title}|{url}")

    return f"{header}{chr(10).join(lines)}"


def _build_page_info_planning_feedback(summary: Dict[str, Any]) -> str:
    return (
        f"GetBrowserPageInfo index {summary.get('index')}; "
        f"active {summary.get('active')}.\n"
        f"Title: {summary.get('title')}\nURL: {summary.get('url')}"
    )


def create_browser_agent_page_actions(
    get_page_manager: Any,
    set_planning_feedback: Optional[Any] = None,
) -> List[Any]:
    """Build the upstream browser page actions.

    ``set_planning_feedback`` is optional because the Python planner does not
    carry upstream's ``context.task.planningFeedback`` channel.
    """
    from midscene.core.device import DeviceAction

    async def list_pages(param: Any, device: Any, locate_fn: Any) -> Any:
        summaries = await get_page_manager().page_summaries()
        offset = (param or {}).get("offset") or 0
        if summaries and offset >= len(summaries):
            raise ValueError(
                f"[midscene] ListBrowserPages offset {offset} is out of range "
                f"for {len(summaries)} pages. Start again with offset 0."
            )
        visible = summaries[offset : offset + PAGE_LIST_SIZE]
        if set_planning_feedback is not None:
            active_index = next(
                (item["index"] for item in summaries if item.get("active")), None
            )
            set_planning_feedback(
                _build_planning_feedback(visible, len(summaries), offset, active_index)
            )
        return visible

    async def get_page_info(param: Any, device: Any, locate_fn: Any) -> Any:
        summary = await get_page_manager().page_summary_by_index(param["index"])
        if set_planning_feedback is not None:
            set_planning_feedback(_build_page_info_planning_feedback(summary))
        return summary

    async def set_active_page(param: Any, device: Any, locate_fn: Any) -> Any:
        await get_page_manager().set_active_page_by_selector(param)
        return None

    return [
        DeviceAction(
            name="ListBrowserPages",
            description=(
                "List open browser pages/tabs in groups of 8 and show which one "
                "is active. Use offset to see the next group before switching pages."
            ),
            param_schema={
                "offset": {
                    "type": "number",
                    "description": "0-based starting position. Omit for the first page.",
                    "optional": True,
                }
            },
            execute=list_pages,
        ),
        DeviceAction(
            name="GetBrowserPageInfo",
            description=(
                "Get the complete title and URL for one browser page/tab without "
                "switching the active page. Use this when ListBrowserPages "
                "truncates details needed to identify a page."
            ),
            param_schema={
                "index": {
                    "type": "number",
                    "description": (
                        "0-based page/tab index returned by ListBrowserPages."
                    ),
                }
            },
            sample={"index": 1},
            execute=get_page_info,
        ),
        DeviceAction(
            name="SetActivePage",
            description=(
                "Set the active browser page/tab by 0-based index, title substring, "
                "or URL substring. When index is combined with title or URL, all "
                "provided values must match the same page. Use index from "
                "ListBrowserPages when more than one page could match."
            ),
            param_schema={
                "index": {
                    "type": "number",
                    "description": (
                        "0-based page/tab index returned by ListBrowserPages."
                    ),
                    "optional": True,
                },
                "title": {
                    "type": "string",
                    "description": "Case-insensitive page title substring to match.",
                    "optional": True,
                },
                "url": {
                    "type": "string",
                    "description": "Case-insensitive page URL substring to match.",
                    "optional": True,
                },
            },
            sample={"index": 1},
            execute=set_active_page,
        ),
    ]


def append_browser_agent_page_actions(
    custom_actions: Optional[List[Any]], browser_actions: List[Any]
) -> List[Any]:
    if not custom_actions:
        return browser_actions
    custom_names = {
        action["name"] if isinstance(action, dict) else action.name
        for action in custom_actions
    }
    return [
        *custom_actions,
        *[
            action
            for action in browser_actions
            if (action["name"] if isinstance(action, dict) else action.name)
            not in custom_names
        ],
    ]


__all__ = [
    "INPUT_STRATEGIES",
    "BrowserPageActionsMixin",
    "_RECT_FOR_XPATH_JS",
    "_XPATHS_AT_POINT_JS",
    "_resolve_text_input_options",
    "append_browser_agent_page_actions",
    "create_browser_agent_page_actions",
]
