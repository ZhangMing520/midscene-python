"""Synced from upstream ``packages/shared/tests/unit-test/tree.test.ts``.

The upstream ``toMatchSnapshot()`` assertions are reproduced against the
checked-in upstream snapshot values (``__snapshots__/tree.test.ts.snap``).
"""

import textwrap
from typing import Any

from midscene.core.tree import description_of_tree
from midscene.core.types import NodeType, Rect, UINode, UITree

STORY = (
    "Legend had it that the Whispering Woods held an ancient secret, one that "
    "connected the world of man and magic, of reality and dream. Each leaf, "
    "every rustling branch, was said to carry the whispers of the ancient "
    "spirits who protected the forest. Elara often spent her evenings perched "
    "on the boundary stones, listening intently to the murmur of the leaves, "
    "wondering what secrets they concealed."
)

IMG_ATTRIBUTES = {
    "nodeType": NodeType.IMAGE,
    "style": "width: 100px; height: 100px;",
    "src": "https://example.com/image.jpg",
    "htmlTagName": "<img>",
    "ariaLabel": "image description",
    "storyContent": STORY,
}


def _node(
    node_id: str,
    content: str,
    node_type: NodeType,
    *,
    width: float = 100,
    height: float = 100,
    is_visible: bool = True,
    attributes: dict[str, Any] | None = None,
) -> UINode:
    return UINode(
        id=node_id,
        content=content,
        rect=Rect(left=0, top=0, width=width, height=height),
        center=(50, 50),
        node_type=node_type,
        attributes=attributes or {},
        is_visible=is_visible,
    )


def _tree(node: UINode, children: list[UITree] | None = None) -> UITree:
    return UITree(node=node, children=children or [])


def _build_tree() -> UITree:
    story_img = dict(IMG_ATTRIBUTES)
    return _tree(
        _node(
            "1",
            STORY,
            NodeType.CONTAINER,
            attributes={"nodeType": NodeType.CONTAINER},
        ),
        [
            _tree(
                _node(
                    "2",
                    "world",
                    NodeType.TEXT,
                    attributes={
                        "nodeType": NodeType.TEXT,
                        "ariaLabel": (
                            "image description, it could be a long text, very "
                            "loooooooooooooooooooooooooooooooooooooooooong"
                        ),
                    },
                )
            ),
            _tree(
                _node(
                    "3",
                    "world 2345",
                    NodeType.IMAGE,
                    attributes=dict(story_img),
                ),
                [
                    _tree(
                        _node(
                            "3",
                            "",
                            NodeType.IMAGE,
                            attributes=dict(story_img),
                        )
                    ),
                    _tree(
                        _node(
                            "3",
                            "",
                            NodeType.IMAGE,
                            width=3,
                            height=3,
                            attributes=dict(story_img),
                        )
                    ),
                    _tree(
                        _node(
                            "3",
                            "",
                            NodeType.CONTAINER,
                            width=3,
                            height=3,
                            attributes={"nodeType": NodeType.CONTAINER},
                        ),
                        [
                            _tree(
                                _node(
                                    "3",
                                    "",
                                    NodeType.IMAGE,
                                    width=3,
                                    height=3,
                                    attributes={"nodeType": NodeType.IMAGE},
                                ),
                                [
                                    _tree(
                                        _node(
                                            "3222",
                                            "world 2345",
                                            NodeType.IMAGE,
                                            attributes=dict(story_img),
                                        )
                                    )
                                ],
                            ),
                            _tree(
                                _node(
                                    "3",
                                    "I am invisible",
                                    NodeType.IMAGE,
                                    is_visible=False,
                                    attributes={"nodeType": NodeType.IMAGE},
                                ),
                                [
                                    _tree(
                                        _node(
                                            "3222",
                                            "I am visible",
                                            NodeType.IMAGE,
                                            attributes=dict(story_img),
                                        )
                                    )
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def test_should_be_able_to_describe_tree():
    """should be able to describe tree"""
    description = description_of_tree(_build_tree())
    expected = textwrap.dedent(
        """\
        <container id="1"  left="0" top="0" width="100" height="100">
          Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ...
          <text id="2" ariaLabel="image description, it could be a long text, very loooooooooooooooooooooooooooooooooooooooooong" left="0" top="0" width="100" height="100">
            world
          </text>
          <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            world 2345
            <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            </img>
              <>
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  world 2345
                </img>
              </>
              <>
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  I am visible
                </img>
              </>
          </img>
        </container>"""
    )
    assert description == expected


def test_should_be_able_to_describe_tree_filter_non_text_content_true():
    """should be able to describe tree, filterNonTextContent = true"""
    description = description_of_tree(_build_tree(), 20, True)
    expected = textwrap.dedent(
        """\
        <container id="1"  left="0" top="0" width="100" height="100">
          Legend had it that t...
          <text id="2" ariaLabel="image description, i..." left="0" top="0" width="100" height="100">
            world
          </text>
          <img id="3" src="https://example.com/..." ariaLabel="image description" storyContent="Legend had it that t..." left="0" top="0" width="100" height="100">
            world 2345
                <img id="3222" src="https://example.com/..." ariaLabel="image description" storyContent="Legend had it that t..." left="0" top="0" width="100" height="100">
                  world 2345
                </img>
                <img id="3222" src="https://example.com/..." ariaLabel="image description" storyContent="Legend had it that t..." left="0" top="0" width="100" height="100">
                  I am visible
                </img>
          </img>
        </container>"""
    )
    assert description == expected


def test_should_be_able_to_describe_tree_visible_only_true():
    """should be able to describe tree, visibleOnly = true"""
    description = description_of_tree(_build_tree(), None, False, True)
    assert "I am invisible" not in description
    assert "I am visible" in description
    expected = textwrap.dedent(
        """\
        <container id="1"  left="0" top="0" width="100" height="100">
          Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ...
          <text id="2" ariaLabel="image description, it could be a long text, very loooooooooooooooooooooooooooooooooooooooooong" left="0" top="0" width="100" height="100">
            world
          </text>
          <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            world 2345
            <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            </img>
              <>
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  world 2345
                </img>
              </>
              <>
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  I am visible
                </img>
              </>
          </img>
        </container>"""
    )
    assert description == expected


def test_should_be_able_to_describe_tree_visible_only_false():
    """should be able to describe tree, visibleOnly = false"""
    description = description_of_tree(_build_tree(), None, False, False)
    assert "I am invisible" in description
    assert "I am visible" in description
    expected = textwrap.dedent(
        """\
        <container id="1"  left="0" top="0" width="100" height="100">
          Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ...
          <text id="2" ariaLabel="image description, it could be a long text, very loooooooooooooooooooooooooooooooooooooooooong" left="0" top="0" width="100" height="100">
            world
          </text>
          <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            world 2345
            <img id="3" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
            </img>
              <>
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  world 2345
                </img>
              </>
              <img id="3"  left="0" top="0" width="100" height="100">
                I am invisible
                <img id="3222" src="https://example.com/image.jpg" ariaLabel="image description" storyContent="Legend had it that the Whispering Woods held an ancient secret, one that connected the world of man and magic, of reality and dream. Each leaf, every ..." left="0" top="0" width="100" height="100">
                  I am visible
                </img>
              </img>
          </img>
        </container>"""
    )
    assert description == expected
