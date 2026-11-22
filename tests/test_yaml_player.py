"""Synced from upstream packages/web-integration/tests/unit-test/yaml/player.test.ts."""

from unittest.mock import patch

import pytest

from tests.core_helpers import MockInterface


class TestYamlPlayer:
    def test_parse_requires_tasks(self):
        from midscene.core.yaml import parse_yaml_script

        with pytest.raises(ValueError) as exc:
            parse_yaml_script("web:\n  url: https://example.com\n")
        assert '"tasks" is required' in str(exc.value)

    @pytest.mark.asyncio
    async def test_player_runs_flow(self):
        from midscene.core.yaml import ScriptPlayer, parse_yaml_script

        script = parse_yaml_script(
            """
tasks:
  - name: t
    flow:
      - aiTap: the test button
      - aiInput:
          locate: the username field
          value: hello
      - sleep: 1
"""
        )
        interface = MockInterface()

        async def fake_locate(locate_param):
            return {"center": (10, 10), "rect": None, "description": "x"}

        agent = _make_agent(interface)
        with patch.object(agent, "_locate_for_action", fake_locate):
            player = ScriptPlayer(script, agent)
            await player.run()

        assert player.status == "done"
        # aiTap + aiInput (Input taps the field first, then types)
        assert interface.tapped == [(10, 10), (10, 10)]
        assert interface.typed == ["hello"]

    @pytest.mark.asyncio
    async def test_yaml_ai_drag_and_drop(self):
        from midscene.core.yaml import ScriptPlayer, parse_yaml_script

        script = parse_yaml_script(
            """
tasks:
  - name: drag
    flow:
      - aiDragAndDrop:
          from:
            prompt: the card
          to:
            prompt: the drop zone
"""
        )

        class DragInterface(MockInterface):
            def __init__(self):
                super().__init__()
                self.dragged = []

            async def drag_and_drop(self, from_point, to_point):
                self.dragged.append((tuple(from_point), tuple(to_point)))

        interface = DragInterface()

        async def fake_locate(locate_param):
            x = 300 if "zone" in locate_param["prompt"] else 100
            return {"center": (x, 50), "rect": None, "description": "x"}

        agent = _make_agent(interface)
        with patch.object(agent, "_locate_for_action", fake_locate):
            await ScriptPlayer(script, agent).run()
        assert interface.dragged == [((100, 50), (300, 50))]



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


@pytest.fixture
def mock_interface():
    return MockInterface()
