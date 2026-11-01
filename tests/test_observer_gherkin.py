"""
Tests for the UI observer (upstream ui-observer.ts) and the Gherkin
scenario runner (upstream run-gherkin-scenario.ts).
"""

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_core import MockInterface


@pytest.fixture
def mock_interface():
    return MockInterface()


def _agent(**options):
    from midscene.core.agent import Agent
    from midscene.core.types import AgentOptions

    return Agent(
        MockInterface(),
        AgentOptions(
            model_config={
                "MIDSCENE_MODEL_NAME": "m",
                "MIDSCENE_MODEL_API_KEY": "k",
                "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
                "MIDSCENE_MODEL_FAMILY": "gpt-5",
            },
            **options,
        ),
    )


class TestGherkin:
    def test_parse_resolves_and_but(self):
        from midscene.core.gherkin import parse_gherkin_scenario

        parsed = parse_gherkin_scenario(
            """
Scenario: login
  Given the login page is open
  When I type 'user' into the username field
  And I type 'pass' into the password field
  Then the dashboard is displayed
"""
        )
        assert parsed["scenario"] == "login"
        keywords = [(s["keyword"], s["effective_keyword"]) for s in parsed["steps"]]
        assert keywords == [
            ("Given", "Given"),
            ("When", "When"),
            ("And", "When"),
            ("Then", "Then"),
        ]

    def test_parse_rejects_feature_header(self):
        from midscene.core.gherkin import parse_gherkin_scenario

        with pytest.raises(ValueError) as exc:
            parse_gherkin_scenario("Feature: x\nGiven a thing")
        assert "does not support" in str(exc.value)

    def test_parse_rejects_orphan_and(self):
        from midscene.core.gherkin import parse_gherkin_scenario

        with pytest.raises(ValueError) as exc:
            parse_gherkin_scenario("And something else")
        assert "cannot resolve" in str(exc.value)

    def test_parse_rejects_multiple_scenarios(self):
        from midscene.core.gherkin import parse_gherkin_scenario

        with pytest.raises(ValueError) as exc:
            parse_gherkin_scenario(
                "Scenario: a\nGiven x\nScenario: b\nGiven y"
            )
        assert "exactly one Scenario" in str(exc.value)

    @pytest.mark.asyncio
    async def test_run_maps_keywords_to_apis(self):
        agent = _agent()
        calls: List[tuple] = []

        async def fake_act(prompt, opt=None):
            calls.append(("act", prompt))

        async def fake_assert(assertion, msg=None, opt=None):
            calls.append(("assert", assertion))

        with patch.object(agent, "ai_act", new=fake_act), patch.object(
            agent, "ai_assert", new=fake_assert
        ):
            await agent.run_gherkin_scenario(
                """
Scenario: flow
  Given a clean cart
  When I add an item
  Then the cart shows the item
"""
            )
        assert calls == [
            ("act", "Set up this precondition: a clean cart"),
            ("act", "Perform this user action: I add an item"),
            ("assert", "the cart shows the item"),
        ]

    @pytest.mark.asyncio
    async def test_run_sets_cacheable_false(self):
        agent = _agent()
        captured: Dict[str, Any] = {}

        async def fake_act(prompt, opt=None):
            captured.update(opt or {})

        with patch.object(agent, "ai_act", new=fake_act):
            await agent.run_gherkin_scenario("When I do a thing")
        assert captured["cacheable"] is False


class TestYamlFlowItems:
    def _script(self, flow_yaml: str):
        from midscene.core.yaml_runner import parse_yaml_script

        return parse_yaml_script(f"tasks:\n  - name: t\n    flow:\n{flow_yaml}")

    @pytest.mark.asyncio
    async def test_finalize_noop(self):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        player = ScriptPlayer(self._script("      - Finalize: true"), agent)
        await player.run()
        assert player.status == "done"

    @pytest.mark.asyncio
    async def test_terminate_maps_to_action(self):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        calls: List[tuple] = []

        async def fake_call(action_type, param):
            calls.append((action_type, param))

        with patch.object(agent, "_call_action_in_action_space", new=fake_call):
            player = ScriptPlayer(
                self._script("      - terminate: com.example.app"), agent
            )
            await player.run()
        assert calls == [("Terminate", {"uri": "com.example.app"})]

    @pytest.mark.asyncio
    async def test_gherkin_flow_item(self):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        with patch.object(agent, "run_gherkin_scenario", new=AsyncMock()) as mock:
            player = ScriptPlayer(
                self._script("      - runGherkinScenario: |\n          Given a page"), agent
            )
            await player.run()
        assert mock.await_count == 1


class TestUIObserver:
    @pytest.mark.asyncio
    async def test_records_frames_and_stops(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing({"intervalMs": 200, "maxFrames": 3, "watchdogMs": 0})
        await observer.start()
        assert observer.buffered_frame_count >= 1
        await asyncio.sleep(0.7)
        observation = await observer.stop()
        assert observation.frame_count >= 2
        # sequence evaluates over recorded frames
        assert len(observation._frames) == observation.frame_count
        await observation.dispose()

    @pytest.mark.asyncio
    async def test_watchdog_auto_stops(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing({"intervalMs": 100, "watchdogMs": 300})
        await observer.start()
        await asyncio.sleep(0.6)
        assert observer._stop_requested is True

    @pytest.mark.asyncio
    async def test_observation_ai_assert_passes_frames(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing({"intervalMs": 100, "maxFrames": 3, "watchdogMs": 0})
        await observer.start()
        await asyncio.sleep(0.25)
        observation = await observer.stop()

        captured: Dict[str, Any] = {}

        async def fake_extract(**kwargs):
            captured.update(kwargs)
            return {
                "parse_result": {"data": {"assertion": True}, "thought": "ok"},
                "usage": None,
            }

        with patch(
            "midscene.core.ai_model.workflows.ai_extract_element_info",
            new=AsyncMock(side_effect=fake_extract),
        ):
            result = await observation.ai_assert("a toast appeared", opt={"keepRawResponse": True})

        assert result["pass"] is True
        sequence = captured["screenshot_sequence"]
        assert len(sequence) == observation.frame_count
        # frozen context carries the full sequence + last frame as current
        assert captured["context"].screenshot_sequence == sequence
        assert captured["context"].screenshot_base64 == sequence[-1]

    @pytest.mark.asyncio
    async def test_dom_included_rejected(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing({"intervalMs": 50, "watchdogMs": 0})
        await observer.start()
        observation = await observer.stop()
        with pytest.raises(ValueError) as exc:
            await observation.ai_boolean("x", {"domIncluded": True})
        assert "domIncluded" in str(exc.value)

    def test_start_observing_rejects_frozen_context(self, mock_interface):
        agent = _agent()
        agent._frozen = True
        with pytest.raises(RuntimeError) as exc:
            agent.start_observing()
        assert "frozen" in str(exc.value)
