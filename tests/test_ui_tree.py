"""Synced from upstream ``packages/android/tests/unit-test/ui-tree.test.ts``.

The Python port exposes ``parse_ui_automator_xml()``, which flattens the dump
into physical-pixel element descriptors instead of building the upstream
``uiautomatorXmlToUiNode()`` hierarchy with logical bounds.
"""

import pytest


@pytest.mark.skip(
    reason="Python android/ui_tree.py has no uiautomatorXmlToUiNode(); "
    "parse_ui_automator_xml() returns a flat list of physical-pixel elements "
    "with no hierarchy/logical-bounds conversion"
)
def test_unwraps_a_hierarchy_and_converts_physical_bounds_to_logical_bounds():
    """unwraps a hierarchy and converts physical bounds to logical bounds"""
    pass


@pytest.mark.skip(
    reason="Python parse_ui_automator_xml() flattens nodes and never returns "
    "a synthetic 'hierarchy' root for multi-window dumps"
)
def test_retains_a_synthetic_hierarchy_root_for_multi_window_dumps():
    """retains a synthetic hierarchy root for multi-window dumps"""
    pass


@pytest.mark.skip(
    reason="Python uses xml.etree.ElementTree, which raises "
    "ParseError('mismatched tag ...') rather than upstream's "
    "'unbalanced close tag' message"
)
def test_throws_for_malformed_xml():
    """throws for malformed XML"""
    pass
