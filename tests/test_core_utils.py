"""Synced from upstream ``packages/core/tests/unit-test/utils.test.ts``.

Upstream exposes coordinate helpers under the ``shrunkShotToLogicalRatio``
describe block (``scales an existing center independently from the retained
rect``).  The Python port performs the inverse conversion, from model/shot
space back to logical viewport space, in ``Agent._to_logical_coords``.
"""


def _agent():
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": "gpt-5",
    }
    return Agent(MockInterface(), AgentOptions(model_config=config))


class TestShrunkShotToLogicalRatio:
    def test_scales_an_existing_center_independently_from_the_retained_rect(self):
        from midscene.core.types import NodeType, Rect, Size, UIContext, UINode, UITree

        context = UIContext(
            screenshot_base64="",
            size=Size(width=320, height=240),
            content=[],
            tree=UITree(
                node=UINode(
                    id="root",
                    content="",
                    rect=Rect(left=0, top=0, width=0, height=0),
                    center=(0, 0),
                    node_type=NodeType.CONTAINER,
                )
            ),
            shrunk_shot_to_logical_ratio=2.0,
        )
        element = {
            "center": (200, 240),
            "rect": {"left": 160, "top": 200, "width": 40, "height": 40},
        }
        scaled = _agent()._to_logical_coords(element, context)
        assert scaled["center"] == [100, 120]
        assert scaled["rect"]["left"] == 80
