"""Element extraction helpers (upstream shared/src/extractor).

The upstream package is DOM-oriented; the Python SDK only ports the
platform-neutral tree/description helpers plus the cross-platform element
descriptor surfaced by `ElementInfo`/`ElementNode`.
"""

from typing import Any, Optional, TypedDict

from midscene.core.types import NodeType, Rect
from midscene.shared.extractor.constants import TEXT_MAX_SIZE, TEXT_SIZE_THRESHOLD
from midscene.shared.extractor.tree import (
    description_of_tree,
    traverse_tree,
    tree_to_list,
    trim_attributes,
    truncate_text,
)
from midscene.shared.extractor.util import (
    get_debug_mode,
    is_element_partially_in_viewport,
    logger,
    overlapped_rect,
    set_debug_mode,
)


class ElementAttributes(TypedDict, total=False):
    nodeType: str


class ElementInfo(TypedDict, total=False):
    """Upstream ElementInfo: a flat description of one extracted element."""

    id: str
    indexId: int
    nodeHashId: str
    xpaths: list[str]
    attributes: dict[str, Any]
    nodeType: NodeType
    content: str
    rect: Rect
    center: Any
    isVisible: bool


class ElementNode(TypedDict):
    """Upstream ElementNode: a node plus its extracted children."""

    node: ElementInfo | None
    children: list["ElementNode"]


__all__ = [
    "TEXT_MAX_SIZE",
    "TEXT_SIZE_THRESHOLD",
    "ElementAttributes",
    "ElementInfo",
    "ElementNode",
    "description_of_tree",
    "traverse_tree",
    "tree_to_list",
    "trim_attributes",
    "truncate_text",
    "get_debug_mode",
    "is_element_partially_in_viewport",
    "logger",
    "overlapped_rect",
    "set_debug_mode",
]
