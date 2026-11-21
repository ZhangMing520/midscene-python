"""UIAutomator XML -> UI node helpers (upstream ui-tree.ts)."""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from midscene.core.types import NodeType, Rect


def parse_bounds(bounds: str) -> Optional[Rect]:
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


def parse_ui_automator_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Flatten a UIAutomator dump into element descriptors.

    The device wraps these descriptors in its own element type, keeping this
    parser independent from the device implementation.
    """
    root = ET.fromstring(xml_content)
    elements: List[Dict[str, Any]] = []

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
    "parse_bounds",
    "get_android_node_type",
    "parse_ui_automator_xml",
]
