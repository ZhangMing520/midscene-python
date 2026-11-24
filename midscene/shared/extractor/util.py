"""Debug and geometry helpers for extraction (upstream extractor/util.ts).

The Python SDK has no DOM runtime; these helpers operate on duck-typed
window/document/node objects so the same geometry and cache semantics can be
reused by DOM shims and tests.
"""

import re
from importlib import import_module
from typing import Any, cast

from loguru import logger as _logger

from midscene.shared.extractor.tree import truncate_text
from midscene.shared.utils import generate_hash_id

MAX_VALUE_LENGTH = 300

ELEMENT_NODE = 1
TEXT_NODE = 3

# Maximum number of cached node entries to prevent memory leaks.
NODE_CACHE_MAX_SIZE = 2000

_debug_mode = False

# Module-level window/document shims.  Upstream reads the browser globals; in
# Python callers may install equivalent objects for DOM-backed integrations.
window: Any | None = None
document: Any | None = None

_node_hash_cache: dict[str, Any] | None = None

_UNSET = object()


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute/key, trying camelCase and snake_case."""
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return default


def _has(obj: Any, *names: str) -> bool:
    if obj is None:
        return False
    if isinstance(obj, dict):
        return any(name in obj for name in names)
    return any(hasattr(obj, name) for name in names)


def _is_htmlelement(element: Any, current_window: Any) -> bool:
    ctor = _get(current_window, "HTMLElement", "html_element", default=None)
    return ctor is not None and isinstance(element, ctor)


def _node_type(node: Any) -> int | None:
    # DOM shims expose the integer nodeType from the platform boundary.
    return cast(int | None, _get(node, "nodeType", "node_type", default=None))


def _node_name(node: Any) -> str:
    value = _get(node, "nodeName", "node_name", default="")
    return value.lower() if isinstance(value, str) else ""


def _computed_style(
    current_window: Any, element: Any, pseudo: str | None = None
) -> Any:
    getter = _get(
        current_window, "getComputedStyle", "get_computed_style", default=None
    )
    if not callable(getter):
        return None
    return getter(element, pseudo) if pseudo is not None else getter(element)


def _style_property(style: Any, name: str) -> Any:
    if style is None:
        return None
    getter = _get(style, "getPropertyValue", "get_property_value", default=None)
    if callable(getter):
        value = getter(name)
        if value not in (None, ""):
            return value
    return _get(style, name, default=None)


def _rect_number(rect: Any, *names: str, default: float = 0.0) -> float:
    value = _get(rect, *names, default=_UNSET)
    if value is _UNSET or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iter_attributes(node: Any) -> list[tuple[str, Any]]:
    attributes = _get(node, "attributes", default=None)
    if not attributes:
        return []
    if isinstance(attributes, dict):
        return list(attributes.items())
    result: list[tuple[str, Any]] = []
    for attribute in attributes:
        name = _get(attribute, "name", "nodeName", "node_name", default="")
        value = _get(
            attribute,
            "value",
            "nodeValue",
            "node_value",
            "textContent",
            "text_content",
            default="",
        )
        result.append((name, value))
    return result


def set_debug_mode(mode: bool) -> None:
    global _debug_mode
    _debug_mode = mode


def get_debug_mode() -> bool:
    return _debug_mode


def logger(_msg: Any = _UNSET, *msg: Any) -> None:
    """Print extraction diagnostics only when debug mode is on (upstream)."""
    if not _debug_mode:
        return
    parts = ([] if _msg is _UNSET else [_msg]) + list(msg)
    _logger.debug(" ".join(str(part) for part in parts))


def overlapped_rect(
    rect1: dict[str, float], rect2: dict[str, float]
) -> dict[str, float] | None:
    """Intersection of two rects, or None when they do not overlap."""
    left = max(rect1["left"], rect2["left"])
    top = max(rect1["top"], rect2["top"])
    right = min(rect1["right"], rect2["right"])
    bottom = min(rect1["bottom"], rect2["bottom"])
    if left < right and top < bottom:
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left,
            "height": bottom - top,
            "x": left,
            "y": top,
            "zoom": 1,
        }
    return None


def _viewport_rect(current_window: Any, current_document: Any) -> dict[str, float]:
    width = _get(current_window, "innerWidth", "inner_width", default=_UNSET)
    height = _get(current_window, "innerHeight", "inner_height", default=_UNSET)
    document_element = _get(
        current_document, "documentElement", "document_element", default=None
    )
    if width is _UNSET or not width:
        width = _get(document_element, "clientWidth", "client_width", default=0)
    if height is _UNSET or not height:
        height = _get(document_element, "clientHeight", "client_height", default=0)
    width = float(width or 0)
    height = float(height or 0)
    return {
        "left": 0.0,
        "top": 0.0,
        "right": width,
        "bottom": height,
        "width": width,
        "height": height,
        "x": 0.0,
        "y": 0.0,
        "zoom": 1,
    }


def is_element_partially_in_viewport(
    rect: dict[str, float],
    viewport_width: float,
    viewport_height: float,
    visible_area_ratio: float = 2 / 3,
) -> bool:
    """True when enough of the element is inside the viewport (upstream)."""
    viewport_rect = {
        "left": 0,
        "top": 0,
        "right": viewport_width,
        "bottom": viewport_height,
        "width": viewport_width,
        "height": viewport_height,
        "x": 0,
        "y": 0,
        "zoom": 1,
    }
    overlap = overlapped_rect(rect, viewport_rect)
    if not overlap:
        return False
    total_area = rect["height"] * rect["width"]
    if total_area <= 0:
        return False
    return (overlap["width"] * overlap["height"]) / total_area >= visible_area_ratio


def _is_element_partially_in_viewport(
    rect: dict[str, float],
    current_window: Any,
    current_document: Any,
    visible_area_ratio: float = 2 / 3,
) -> bool:
    viewport_rect = _viewport_rect(current_window, current_document)
    overlap = overlapped_rect(rect, viewport_rect)
    if not overlap:
        return False
    total_area = rect["height"] * rect["width"]
    if total_area <= 0:
        return False
    return (overlap["width"] * overlap["height"]) / total_area >= visible_area_ratio


def get_pseudo_element_content(element: Any, current_window: Any) -> dict[str, str]:
    """Return the ``::before``/``::after`` text content of an element."""
    if not _is_htmlelement(element, current_window):
        return {"before": "", "after": ""}
    before_content = _style_property(
        _computed_style(current_window, element, "::before"), "content"
    )
    after_content = _style_property(
        _computed_style(current_window, element, "::after"), "content"
    )
    return {
        "before": ""
        if before_content in (None, "none")
        else str(before_content).replace('"', ""),
        "after": ""
        if after_content in (None, "none")
        else str(after_content).replace('"', ""),
    }


def has_overflow_y(element: Any, current_window: Any) -> bool:
    """True when the element's computed ``overflow-y`` clips content."""
    style = _computed_style(current_window, element)
    overflow_y = _get(style, "overflowY", "overflow_y", default=None)
    return overflow_y in ("scroll", "auto", "hidden")


def get_rect(el: Any, base_zoom: float, current_window: Any) -> dict[str, float]:
    """Compute the zoom-adjusted bounding rect of a node (upstream getRect)."""
    new_zoom = 1.0

    get_bounding_rect = _get(
        el, "getBoundingClientRect", "get_bounding_client_rect", default=None
    )
    if not callable(get_bounding_rect):
        current_document = _get(current_window, "document", default=None)
        create_range = _get(
            current_document, "createRange", "create_range", default=None
        )
        if not callable(create_range):
            raise AttributeError(
                "node has no getBoundingClientRect and the document cannot "
                "create a Range"
            )
        range_ = create_range()
        select_node_contents = _get(
            range_, "selectNodeContents", "select_node_contents", default=None
        )
        if callable(select_node_contents):
            select_node_contents(el)
        original_rect = _get(
            range_, "getBoundingClientRect", "get_bounding_client_rect"
        )
    else:
        original_rect = get_bounding_rect()
        if _is_htmlelement(el, current_window) and not _has(
            el, "currentCSSZoom", "current_css_zoom"
        ):
            zoom_value = _get(_computed_style(current_window, el), "zoom", default=None)
            try:
                new_zoom = float(zoom_value) if zoom_value not in (None, "") else 1.0
            except (TypeError, ValueError):
                new_zoom = 1.0

    zoom = new_zoom * base_zoom
    left = _rect_number(original_rect, "left")
    top = _rect_number(original_rect, "top")
    width = _rect_number(original_rect, "width")
    height = _rect_number(original_rect, "height")
    right = _rect_number(original_rect, "right", default=left + width)
    bottom = _rect_number(original_rect, "bottom", default=top + height)
    x = _rect_number(original_rect, "x", default=left)
    y = _rect_number(original_rect, "y", default=top)

    return {
        "width": width * zoom,
        "height": height * zoom,
        "left": left * zoom,
        "top": top * zoom,
        "right": right * zoom,
        "bottom": bottom * zoom,
        "x": x * zoom,
        "y": y * zoom,
        "zoom": zoom,
    }


def _is_element_covered(el: Any, rect: dict[str, float], current_window: Any) -> bool:
    x = rect["left"] + rect["width"] / 2
    y = rect["top"] + rect["height"] / 2

    current_document = _get(current_window, "document", default=None)
    element_from_point = _get(
        current_document, "elementFromPoint", "element_from_point", default=None
    )
    top_element = element_from_point(x, y) if callable(element_from_point) else None
    if not top_element:
        return False
    if top_element is el:
        return False
    contains = _get(el, "contains", default=None)
    if callable(contains) and contains(top_element):
        return False
    top_contains = _get(top_element, "contains", default=None)
    if callable(top_contains) and top_contains(el):
        return False

    rect_of_top_element = get_rect(top_element, 1, current_window)
    overlap_rect = overlapped_rect(rect, rect_of_top_element)
    if not overlap_rect:
        return False

    logger(el, "Element is covered by another element")
    return True


def _parent_until_non_static(current_node: Any, current_window: Any) -> Any:
    parent = _get(current_node, "parentElement", "parent_element", default=None)
    while parent:
        style = _computed_style(current_window, parent)
        if _get(style, "position", default=None) != "static":
            return parent
        parent = _get(parent, "parentElement", "parent_element", default=None)
    return None


def element_rect(
    el: Any,
    current_window: Any,
    current_document: Any,
    base_zoom: float = 1,
) -> Any:
    """Return the visible rect of an element, or False when it is hidden."""
    if not el:
        logger(el, "Element is not in the DOM hierarchy")
        return False

    if (
        not _is_htmlelement(el, current_window)
        and _node_type(el) != TEXT_NODE
        and _node_name(el) != "svg"
    ):
        logger(el, "Element is not in the DOM hierarchy")
        return False

    if _is_htmlelement(el, current_window):
        style = _computed_style(current_window, el)
        tag_name = str(_get(el, "tagName", "tag_name", default="")).upper()
        opacity = _get(style, "opacity", default=None)
        opacity_is_zero = opacity in (0, 0.0, "0")
        if (
            _get(style, "display", default=None) == "none"
            or _get(style, "visibility", default=None) == "hidden"
            or (opacity_is_zero and tag_name != "INPUT")
        ):
            logger(el, "Element is hidden")
            return False

    rect = get_rect(el, base_zoom, current_window)

    if rect["width"] == 0 and rect["height"] == 0:
        logger(el, "Element has no size")
        return False

    if base_zoom == 1 and _is_element_covered(el, rect, current_window):
        return False

    is_visible = _is_element_partially_in_viewport(
        rect, current_window, current_document
    )

    body = _get(current_document, "body", default=None)
    parent = el
    while parent and parent is not body:
        if not _is_htmlelement(parent, current_window):
            parent = _get(parent, "parentElement", "parent_element", default=None)
            continue
        parent_style = _computed_style(current_window, parent)
        if _get(parent_style, "overflow", default=None) == "hidden":
            parent_rect = get_rect(parent, 1, current_window)
            tolerance = 10
            if (
                rect["right"] < parent_rect["left"] - tolerance
                or rect["left"] > parent_rect["right"] + tolerance
                or rect["bottom"] < parent_rect["top"] - tolerance
                or rect["top"] > parent_rect["bottom"] + tolerance
            ):
                logger(el, "element is partially or totally hidden by an ancestor")
                return False
        position = _get(parent_style, "position", default=None)
        if position in ("fixed", "sticky"):
            break
        if position == "absolute":
            parent = _parent_until_non_static(parent, current_window)
        else:
            parent = _get(parent, "parentElement", "parent_element", default=None)

    return {
        "left": round(rect["left"]),
        "top": round(rect["top"]),
        "width": round(rect["width"]),
        "height": round(rect["height"]),
        "zoom": rect["zoom"],
        "isVisible": is_visible,
    }


def valid_text_node_content(node: Any) -> Any:
    """Return trimmed text for element/text nodes, or False (upstream)."""
    if not node:
        return False
    if (
        _node_type(node) not in (ELEMENT_NODE, TEXT_NODE)
        and _node_name(node) != "#text"
    ):
        return False

    content = _get(node, "textContent", "text_content", default=None) or _get(
        node, "innerText", "inner_text", default=None
    )
    if content and not re.match(r"^\s*$", content):
        return content.strip()
    return False


def get_node_attributes(node: Any, current_window: Any) -> dict[str, str]:
    """Return trimmed node attributes keyed by name (upstream)."""
    if not node or not _is_htmlelement(node, current_window):
        return {}
    if not _get(node, "attributes", default=None):
        return {}

    result: dict[str, str] = {}
    for name, raw_value in _iter_attributes(node):
        value = "" if raw_value is None else str(raw_value)
        if name == "class":
            value = f".{'.'.join(value.split(' '))}"
        else:
            if value.startswith("data:image"):
                value = "image"
            if len(value) > MAX_VALUE_LENGTH:
                value = f"{value[:MAX_VALUE_LENGTH]}..."
        result[name] = value
    return result


def _get_node_cache_map() -> dict[str, Any] | None:
    if window is None:
        return None
    return _node_hash_cache


def set_node_hash_cache_list_on_window() -> None:
    """Reset the node hash cache for a new extraction cycle (upstream)."""
    global _node_hash_cache
    if window is not None:
        _node_hash_cache = {}


def set_node_to_cache_list(node: Any, id: str) -> None:
    """Cache ``node`` under ``id``, evicting the oldest entry if needed."""
    cache = _get_node_cache_map()
    if cache is None:
        return
    if id in cache:
        return
    if len(cache) >= NODE_CACHE_MAX_SIZE:
        first_key = next(iter(cache), None)
        if first_key is not None:
            del cache[first_key]
    cache[id] = node


def get_node_from_cache_list(id: str) -> Any:
    """Return the cached node for ``id``, or None when absent."""
    cache = _get_node_cache_map()
    if cache is None:
        return None
    return cache.get(id)


def midscene_generate_hash(node: Any, content: str, rect: Any) -> str:
    """Hash content+rect and cache the node under the hash (upstream)."""
    sliced_hash = generate_hash_id(rect, content)

    if node is not None:
        if window is not None and _node_hash_cache is None:
            set_node_hash_cache_list_on_window()
        set_node_to_cache_list(node, sliced_hash)

    return sliced_hash


def generate_id(number_id: Any) -> str:
    """Stringify a numeric id (upstream generateId)."""
    if isinstance(number_id, bool):
        return str(number_id).lower()
    if isinstance(number_id, float) and number_id.is_integer():
        number_id = int(number_id)
    return f"{number_id}"


def _set_window_attribute(name: str, value: Any) -> None:
    if window is None:
        return
    if isinstance(window, dict):
        window[name] = value
    else:
        setattr(window, name, value)


def _resolve_extract_text_with_position() -> Any | None:
    existing = globals().get("extract_text_with_position")
    if existing is not None:
        return existing
    try:
        # Optional integration: keep its untyped implementation behind a dynamic
        # module boundary rather than importing it eagerly.
        module = import_module("midscene.shared.extractor.web_extractor")
    except ImportError:
        return None
    return module.extract_text_with_position


def set_generate_hash_on_window() -> None:
    """Expose ``midsceneGenerateHash`` on the window shim (upstream)."""
    _set_window_attribute("midsceneGenerateHash", midscene_generate_hash)


def set_midscene_visible_rect_on_window() -> None:
    """Expose ``midsceneVisibleRect`` on the window shim (upstream)."""
    _set_window_attribute("midsceneVisibleRect", element_rect)


def set_extract_text_with_position_on_window() -> None:
    """Expose ``extractTextWithPosition`` on the window shim (upstream)."""
    extractor = _resolve_extract_text_with_position()
    if extractor is not None:
        _set_window_attribute("extractTextWithPosition", extractor)


def get_top_document() -> Any:
    """Return the top document's body, falling back to the document."""
    if document is None:
        return None
    body = _get(document, "body", default=None)
    return body or document


def trim_attribute_value(value: str) -> str:
    """Shorten image data URLs and oversized attribute values (upstream)."""
    if value.startswith("data:image"):
        return "image"
    if len(value) > MAX_VALUE_LENGTH:
        return f"{truncate_text(value, MAX_VALUE_LENGTH)}..."
    return value


__all__ = [
    "ELEMENT_NODE",
    "MAX_VALUE_LENGTH",
    "NODE_CACHE_MAX_SIZE",
    "TEXT_NODE",
    "document",
    "element_rect",
    "generate_id",
    "get_debug_mode",
    "get_node_attributes",
    "get_node_from_cache_list",
    "get_pseudo_element_content",
    "get_rect",
    "get_top_document",
    "has_overflow_y",
    "is_element_partially_in_viewport",
    "logger",
    "midscene_generate_hash",
    "overlapped_rect",
    "set_debug_mode",
    "set_extract_text_with_position_on_window",
    "set_generate_hash_on_window",
    "set_midscene_visible_rect_on_window",
    "set_node_hash_cache_list_on_window",
    "set_node_to_cache_list",
    "trim_attribute_value",
    "valid_text_node_content",
    "window",
]
