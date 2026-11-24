"""UI tree description facade (upstream packages/core/src/tree.ts)."""

from loguru import logger

from midscene.core.types import UITree
from midscene.shared.extractor.tree import (
    description_of_tree as _description_of_tree,
)
from midscene.shared.extractor.tree import (
    tree_to_list,
    trim_attributes,
    truncate_text,
)

ELEMENT_COUNT_WARNING_THRESHOLD = 5000
TREE_SIZE_WARNING_MESSAGE = (
    "The number of elements is too large, it may cause the prompt to be too "
    'long, please use domIncluded: "visible-only" to reduce the number of '
    "elements"
)


def description_of_tree(
    tree: UITree,
    truncate_text_length: int | None = None,
    filter_non_text_content: bool = False,
    visible_only: bool = True,
) -> str:
    """Describe a UI tree, warning when the unfiltered tree is very large."""
    if not visible_only:
        flat_elements = tree_to_list(tree)
        if len(flat_elements) >= ELEMENT_COUNT_WARNING_THRESHOLD:
            logger.warning(TREE_SIZE_WARNING_MESSAGE)

    return _description_of_tree(
        tree,
        truncate_text_length,
        filter_non_text_content,
        visible_only,
    )


__all__ = [
    "ELEMENT_COUNT_WARNING_THRESHOLD",
    "TREE_SIZE_WARNING_MESSAGE",
    "description_of_tree",
    "tree_to_list",
    "trim_attributes",
    "truncate_text",
]
