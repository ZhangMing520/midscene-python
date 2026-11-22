"""Synced from upstream ``packages/android/tests/unit-test/ui-tree.test.ts``."""

import pytest

from midscene.android.ui_tree import uiautomator_xml_to_ui_node


def test_unwraps_a_hierarchy_and_converts_physical_bounds_to_logical_bounds():
    """unwraps a hierarchy and converts physical bounds to logical bounds"""
    root = uiautomator_xml_to_ui_node(
        """<?xml version="1.0"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.example" bounds="[0,0][400,800]">
    <node class="android.widget.Button" resource-id="submit" text="Pay &amp; continue" bounds="[20,40][180,100]"/>
  </node>
</hierarchy>""",
        2,
    )

    assert root.type == "android.widget.FrameLayout"
    assert root.attrs["package"] == "com.example"
    assert root.attrs["class"] == "android.widget.FrameLayout"
    assert (
        root.bounds.left,
        root.bounds.top,
        root.bounds.width,
        root.bounds.height,
    ) == (0, 0, 200, 400)
    assert len(root.children) == 1
    child = root.children[0]
    assert child.type == "android.widget.Button"
    assert child.attrs["resource-id"] == "submit"
    assert child.attrs["text"] == "Pay & continue"
    assert child.attrs["class"] == "android.widget.Button"
    assert (
        child.bounds.left,
        child.bounds.top,
        child.bounds.width,
        child.bounds.height,
    ) == (10, 20, 80, 30)
    assert "bounds" not in root.attrs


def test_retains_a_synthetic_hierarchy_root_for_multi_window_dumps():
    """retains a synthetic hierarchy root for multi-window dumps"""
    root = uiautomator_xml_to_ui_node(
        """<hierarchy>
        <node class="WindowA" bounds="[0,0][100,100]"/>
        <node class="WindowB" bounds="[100,0][200,100]"/>
      </hierarchy>""",
        1,
    )

    assert root.type == "hierarchy"
    assert [child.type for child in root.children] == ["WindowA", "WindowB"]


def test_throws_for_malformed_xml():
    """throws for malformed XML"""
    with pytest.raises(ValueError, match="unbalanced close tag"):
        uiautomator_xml_to_ui_node("<hierarchy><node></hierarchy>", 1)
