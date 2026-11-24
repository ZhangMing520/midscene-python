"""Synced from upstream packages/web-integration/tests/unit-test/
web-actions-navigation.test.ts and bridge/io.test.ts."""


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


class TestWebPageActions:
    def test_bridge_action_space_matches_extension_primitives(self):
        from midscene.web_integration.bridge_mode import BridgeWebPage

        names = {action.name for action in _make_agent(BridgeWebPage()).action_space}
        assert {
            "Tap",
            "RightClick",
            "MiddleClick",
            "DoubleClick",
            "Hover",
            "DragAndDrop",
            "KeyboardPress",
            "Scroll",
            "Input",
            "Pinch",
            "ClearInput",
            "CursorMove",
            "Navigate",
            "Reload",
            "GoBack",
            "GoForward",
        } <= names
