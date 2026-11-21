"""Tree helpers for element descriptions (upstream extractor/tree.ts)."""

import json
from typing import Any, Callable, Dict, List, Optional, Union

from midscene.core.types import UINode, UITree

NODE_SIZE_THRESHOLD = 4


def truncate_text(
    text: Union[str, int, float, object, None], max_length: int = 150
) -> str:
    """Stringify and truncate an attribute value (upstream truncateText)."""
    if text is None:
        return ""
    if isinstance(text, bool):
        return str(text).lower()
    if isinstance(text, (int, float)):
        return str(text)
    if isinstance(text, (dict, list, tuple)):
        text = json.dumps(text)
    value = str(text)
    if len(value) > max_length:
        return f"{value[:max_length]}..."
    return value.strip()


def trim_attributes(
    attributes: Dict[str, Any], truncate_text_length: Optional[int] = None
) -> Dict[str, str]:
    """Drop rendering-only attributes and truncate the rest (upstream)."""
    result: Dict[str, str] = {}
    for key, value in attributes.items():
        if key in ("style", "htmlTagName", "nodeType"):
            continue
        result[key] = truncate_text(value, truncate_text_length or 150)
    return result


def description_of_tree(
    tree: UITree,
    truncate_text_length: Optional[int] = None,
    filter_non_text_content: bool = False,
    visible_only: bool = True,
) -> str:
    """Render a UI tree as the XML-ish description fed to the model."""

    def attributes_string(kv: Dict[str, Any]) -> str:
        return " ".join(
            f'{key}="{truncate_text(value, truncate_text_length or 150)}"'
            for key, value in kv.items()
        )

    def build_content_tree(
        node: UITree, indent: int = 0, only_visible: bool = True
    ) -> str:
        before = ""
        content_with_indent = ""
        after = ""
        empty_node = True
        indent_str = "  " * indent

        children = ""
        for child in node.children:
            child_content = build_content_tree(child, indent + 1, only_visible)
            if child_content:
                children += f"\n{child_content}"

        current = node.node
        if (
            current is not None
            and current.rect.width > NODE_SIZE_THRESHOLD
            and current.rect.height > NODE_SIZE_THRESHOLD
            and (not filter_non_text_content or bool(current.content))
            and (not only_visible or current.is_visible)
        ):
            empty_node = False
            html_tag_name = current.attributes.get("htmlTagName")
            if html_tag_name:
                node_type_string = str(html_tag_name).replace("<", "").replace(">", "")
            else:
                node_type = getattr(current.node_type, "value", current.node_type)
                node_type_string = str(node_type).lower()
            rect_attributes = {
                "left": current.rect.left,
                "top": current.rect.top,
                "width": current.rect.width,
                "height": current.rect.height,
            }
            before = (
                f'<{node_type_string} id="{current.id}" '
                f"{attributes_string(trim_attributes(current.attributes, truncate_text_length))} "
                f"{attributes_string(rect_attributes)}>"
            )
            content = truncate_text(current.content, truncate_text_length or 150)
            content_with_indent = f"\n{indent_str}  {content}" if content else ""
            after = f"</{node_type_string}>"
        elif not filter_non_text_content and not children.strip().startswith("<>"):
            before = "<>"
            after = "</>"

        if empty_node and not children.strip():
            return ""

        result = f"{indent_str}{before}{content_with_indent}{children}\n{indent_str}{after}"
        return result if result.strip() else ""

    return build_content_tree(tree, 0, visible_only)


def tree_to_list(tree: UITree) -> List[UINode]:
    """Flatten a UI tree into its nodes in depth-first order."""
    result: List[UINode] = []

    def dfs(node: UITree) -> None:
        if node.node is not None:
            result.append(node.node)
        for child in node.children:
            dfs(child)

    dfs(tree)
    return result


def traverse_tree(
    tree: UITree, on_node: Callable[[UINode], UINode]
) -> UITree:
    """Map every node through `on_node` in place (upstream traverseTree)."""

    def dfs(node: UITree) -> None:
        if node.node is not None:
            node.node = on_node(node.node)
        for child in node.children:
            dfs(child)

    dfs(tree)
    return tree


__all__ = [
    "NODE_SIZE_THRESHOLD",
    "truncate_text",
    "trim_attributes",
    "description_of_tree",
    "tree_to_list",
    "traverse_tree",
]
