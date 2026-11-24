"""UIAutomator XML -> UI node helpers (upstream ui-tree.ts)."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from midscene.core.types import NodeType, Rect


@dataclass
class UiNode:
    """Upstream core ``UiNode`` shape (type/attrs/bounds/children)."""

    type: str
    attrs: dict[str, str] = field(default_factory=dict)
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    children: list["UiNode"] = field(default_factory=list)


_TAG_RE = re.compile(r"<(\/?)([A-Za-z_][A-Za-z0-9_.\-:]*)([^>]*?)(\/?)>")
_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.\-:]*)\s*=\s*(\"([^\"]*)\"|'([^']*)')")
_BOUNDS_RE = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")
_ENTITY_TABLE = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
}


def _decode_entities(value: str) -> str:
    if "&" not in value:
        return value

    def replace(match: "re.Match[str]") -> str:
        body = match.group(1)
        try:
            if body[:2] in ("#x", "#X"):
                return chr(int(body[2:], 16))
            if body.startswith("#"):
                return chr(int(body[1:], 10))
        except (ValueError, OverflowError):
            return match.group(0)
        return _ENTITY_TABLE.get(body, match.group(0))

    return re.sub(r"&(#x?[0-9a-fA-F]+|[a-zA-Z]+);", replace, value)


def _parse_attrs(raw: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw):
        attrs[match.group(1)] = _decode_entities(
            match.group(3) if match.group(3) is not None else (match.group(4) or "")
        )
    return attrs


@dataclass
class _XmlElement:
    name: str
    attrs: dict[str, str]
    children: list["_XmlElement"] = field(default_factory=list)


def _parse_xml(input_text: str) -> _XmlElement:
    if input_text.strip() == "":
        raise ValueError("parseAndroidUITreeXml: input is empty")

    cleaned = re.sub(r"<\?xml[\s\S]*?\?>", "", input_text)
    cleaned = re.sub(r"<!DOCTYPE[\s\S]*?>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<!--[\s\S]*?-->", "", cleaned)

    stack: list[_XmlElement] = []
    root: _XmlElement | None = None

    for match in _TAG_RE.finditer(cleaned):
        is_close = match.group(1) == "/"
        name = match.group(2)
        if is_close:
            current = stack.pop() if stack else None
            if current is None or current.name != name:
                raise ValueError(
                    f"parseAndroidUITreeXml: unbalanced close tag </{name}>"
                )
            continue

        element = _XmlElement(name=name, attrs=_parse_attrs(match.group(3) or ""))
        if stack:
            stack[-1].children.append(element)
        elif root is not None:
            raise ValueError("parseAndroidUITreeXml: more than one top-level element")
        else:
            root = element

        if match.group(4) != "/":
            stack.append(element)

    if stack:
        raise ValueError("parseAndroidUITreeXml: unclosed element")
    if root is None:
        raise ValueError("parseAndroidUITreeXml: no root element")
    return root


def _parse_ui_bounds(raw: str | None, device_pixel_ratio: float) -> Rect:
    match = _BOUNDS_RE.match(raw) if raw else None
    if not match:
        return Rect(left=0, top=0, width=0, height=0)
    left = int(match.group(1))
    top = int(match.group(2))
    right = int(match.group(3))
    bottom = int(match.group(4))
    ratio = device_pixel_ratio if device_pixel_ratio > 0 else 1
    return Rect(
        left=left / ratio,
        top=top / ratio,
        width=max(0, right - left) / ratio,
        height=max(0, bottom - top) / ratio,
    )


def _to_ui_node(element: _XmlElement, device_pixel_ratio: float) -> UiNode:
    attrs = {name: value for name, value in element.attrs.items() if name != "bounds"}
    return UiNode(
        type=element.attrs.get("class") or element.name,
        attrs=attrs,
        bounds=_parse_ui_bounds(element.attrs.get("bounds"), device_pixel_ratio),
        children=[_to_ui_node(child, device_pixel_ratio) for child in element.children],
    )


def uiautomator_xml_to_ui_node(xml: str, device_pixel_ratio: float) -> UiNode:
    """Parse a UIAutomator dump into the upstream UiNode hierarchy."""
    root = _parse_xml(xml)
    if root.name == "hierarchy" and len(root.children) == 1:
        return _to_ui_node(root.children[0], device_pixel_ratio)
    return _to_ui_node(root, device_pixel_ratio)


def parse_bounds(bounds: str) -> Rect | None:
    """Parse a UIAutomator `[x1,y1][x2,y2]` bounds string."""
    if not bounds:
        return None
    coords = bounds.replace("][", ",").replace("[", "").replace("]", "").split(",")
    if len(coords) != 4:
        return None
    x1, y1, x2, y2 = map(int, coords)
    return Rect(left=x1, top=y1, width=x2 - x1, height=y2 - y1)


def get_android_node_type(class_name: str) -> NodeType:
    """Map an Android widget class name onto the shared node types."""
    lowered = class_name.lower()
    if "button" in lowered:
        return NodeType.BUTTON
    if "edittext" in lowered or "textfield" in lowered:
        return NodeType.INPUT
    if "textview" in lowered or "text" in lowered:
        return NodeType.TEXT
    if "imageview" in lowered or "image" in lowered:
        return NodeType.IMAGE
    if (
        "linearlayout" in lowered
        or "relativelayout" in lowered
        or "framelayout" in lowered
    ):
        return NodeType.CONTAINER
    return NodeType.OTHER


def parse_ui_automator_xml(xml_content: str) -> list[dict[str, Any]]:
    """Flatten a UIAutomator dump into element descriptors.

    The device wraps these descriptors in its own element type, keeping this
    parser independent from the device implementation.
    """
    root = ET.fromstring(xml_content)
    elements: list[dict[str, Any]] = []

    def parse_node(node) -> None:
        if node.tag == "node":
            rect = parse_bounds(node.get("bounds", ""))
            if rect is not None:
                class_name = node.get("class", "")
                content = node.get("text", "") or node.get("content-desc", "")
                is_visible = rect.width > 0 and rect.height > 0
                if is_visible:
                    elements.append(
                        {
                            "content": content,
                            "rect": rect,
                            "center": (
                                rect.left + rect.width / 2,
                                rect.top + rect.height / 2,
                            ),
                            "node_type": get_android_node_type(class_name),
                            "attributes": {
                                "class": class_name,
                                "package": node.get("package", ""),
                                "clickable": node.get("clickable", "false") == "true",
                                "enabled": node.get("enabled", "false") == "true",
                                "focused": node.get("focused", "false") == "true",
                                "selected": node.get("selected", "false") == "true",
                            },
                            "is_visible": is_visible,
                        }
                    )
        for child in node:
            parse_node(child)

    parse_node(root)
    return elements


__all__ = [
    "UiNode",
    "parse_bounds",
    "get_android_node_type",
    "parse_ui_automator_xml",
    "uiautomator_xml_to_ui_node",
]
