"""Synced from upstream packages/core/tests/unit-test/device/input-primitives.test.ts."""


def _make_agent(interface):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

    return Agent(
        interface,
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "mock-model",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            }
        ),
    )


class TestDeviceInputPrimitives:
    def test_actions_require_device_primitives(self):
        class TapOnlyInterface:
            interface_type = "web"

            async def tap(self, x, y):
                pass

        names = {action.name for action in _make_agent(TapOnlyInterface()).action_space}
        assert "Tap" in names
        assert "RightClick" not in names
        assert "MiddleClick" not in names
        assert "Scroll" not in names

    def test_action_space_ignores_unimplemented_stubs(self):
        from midscene.core.types import AbstractInterface, InterfaceType

        class StubInterface(AbstractInterface):
            @property
            def interface_type(self):
                return InterfaceType.WEB

            async def get_context(self):
                return None

            async def action_space(self):
                return []

            async def tap(self, x, y):
                pass

            async def input_text(self, text):
                pass

            async def scroll(self, direction, distance=None, **kwargs):
                pass

        names = {action.name for action in _make_agent(StubInterface()).action_space}
        assert {"Tap", "Input", "Scroll"} <= names
        assert "DragAndDrop" not in names
        assert "RightClick" not in names

