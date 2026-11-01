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
            # upstream asserts the built prompt, not the bare step text
            ("assert", "Verify that the cart shows the item"),
        ]

    @pytest.mark.asyncio
    async def test_run_passes_assert_context_only_when_set(self):
        agent = _agent()
        seen: List[Any] = []

        async def fake_assert(assertion, msg=None, opt=None):
            seen.append(opt)

        with patch.object(agent, "ai_assert", new=fake_assert):
            await agent.run_gherkin_scenario("Then the cart is empty")
        assert seen == [None]

        with patch.object(agent, "ai_assert", new=fake_assert):
            await agent.run_gherkin_scenario(
                "Then the cart is empty", {"context": "extra hint"}
            )
        assert seen == [None, {"context": "extra hint"}]

    @pytest.mark.asyncio
    async def test_run_wraps_step_failure_with_line(self):
        agent = _agent()

        async def failing_act(prompt, opt=None):
            raise RuntimeError("model unavailable")

        with patch.object(agent, "ai_act", new=failing_act):
            with pytest.raises(RuntimeError) as exc:
                await agent.run_gherkin_scenario(
                    "Scenario: flow\n  When I add an item\n  Then it shows"
                )
        message = str(exc.value)
        assert "runGherkinScenario failed while" in message
        assert "performing the user action (When -> aiAct)" in message
        assert "at line 2: When I add an item" in message
        assert "model unavailable" in message
        assert isinstance(exc.value.__cause__, RuntimeError)

    @pytest.mark.asyncio
    async def test_run_resolves_and_keyword_in_message(self):
        agent = _agent()

        async def fake_act(prompt, opt=None):
            if "a dialog" in prompt:
                raise RuntimeError("boom")

        with patch.object(agent, "ai_act", new=fake_act):
            with pytest.raises(RuntimeError) as exc:
                await agent.run_gherkin_scenario(
                    "Scenario: flow\n  Given a page\n  And a dialog"
                )
        assert (
            "setting up the precondition (And as Given -> aiAct) at line 3"
            in str(exc.value)
        )

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
    async def test_launch_maps_to_action(self):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        calls: List[tuple] = []

        async def fake_call(action_type, param):
            calls.append((action_type, param))

        with patch.object(agent, "_call_action_in_action_space", new=fake_call):
            player = ScriptPlayer(
                self._script("      - launch: https://example.com"), agent
            )
            await player.run()
        assert calls == [("Launch", {"uri": "https://example.com"})]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [True, 123, None, {"uri": {"a": 1}}, "  "])
    async def test_launch_rejects_non_string_uri(self, value):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        player = ScriptPlayer(self._script("      - launch: com.example.app"), agent)
        with pytest.raises(ValueError) as exc:
            await player._run_flow_item("launch", value)
        assert "launch requires a non-empty uri string" in str(exc.value)

    @pytest.mark.asyncio
    async def test_bad_uri_fails_the_task(self):
        from midscene.core.yaml_runner import ScriptPlayer

        agent = _agent()
        player = ScriptPlayer(self._script("      - terminate: true"), agent)
        await player.run()
        assert player.status == "error"

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
    def _tagged_contexts(self, agent, state, fail_first=0):
        """Return distinct frame tags, optionally failing the first captures."""

        async def fake_context(action=""):
            base = await agent.interface.get_context()
            state["n"] += 1
            if state["n"] <= fail_first:
                raise RuntimeError("capture exploded")
            return base.model_copy(update={"screenshot_base64": f"frame-{state['n']}"})

        agent.get_ui_context = fake_context

    @pytest.mark.asyncio
    async def test_start_survives_first_capture_failure(self, mock_interface):
        agent = _agent()
        state = {"n": 0}
        self._tagged_contexts(agent, state, fail_first=2)
        observer = agent.start_observing(
            {"intervalMs": 150, "maxFrames": 30, "watchdogMs": 0}
        )
        # a failing first screenshot must not abort the recording window
        await observer.start()
        await asyncio.sleep(0.5)
        observation = await observer.stop()
        assert observation.frame_count >= 1
        assert observation._frames[0] == "frame-3"
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_keeps_sampling_past_max_frames(self, mock_interface):
        agent = _agent()
        state = {"n": 0}
        self._tagged_contexts(agent, state)
        observer = agent.start_observing(
            {"intervalMs": 150, "maxFrames": 4, "watchdogMs": 0}
        )
        await observer.start()
        await asyncio.sleep(1.5)
        observation = await observer.stop()
        # the window keeps being sampled past the cap; the buffer is thinned
        assert state["n"] > 4
        assert observation.frame_count <= 4
        assert observation._frames[-1] == f"frame-{state['n']}"
        await observer.dispose()

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
        # the auto-stop must really produce a window, not only flip the flag
        observation = await observer.stop()
        assert observation is observer._observation
        assert observation.frame_count >= 1
        await observer.dispose()

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

    @pytest.mark.asyncio
    async def test_concurrent_stops_share_one_window(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
        )
        await observer.start()
        first, second = await asyncio.gather(observer.stop(), observer.stop())
        assert first is second
        assert first.frame_count >= 1
        await observer.dispose()

    @pytest.mark.asyncio
    async def test_observation_owns_its_frames(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
        )
        await observer.start()
        observation = await observer.stop()
        assert observation._frames is not observer._frames
        await observer.dispose()
        # disposing the observer also releases the window it handed out
        assert observer._frames == []
        assert observation._disposed is True
        with pytest.raises(RuntimeError) as exc:
            await observation.ai_boolean("anything")
        assert "disposed" in str(exc.value)

    @pytest.mark.asyncio
    async def test_dispose_before_stop_releases_frames(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
        )
        await observer.start()
        await observer.dispose()
        assert observer._stop_requested is True
        assert observer._frames == []

    @pytest.mark.asyncio
    async def test_dispose_joins_an_unawaited_stop(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 5, "watchdogMs": 0}
        )
        await observer.start()
        observer.stop()  # never awaited by the caller
        await observer.dispose()
        assert observer._observation is not None
        assert observer._observation._disposed is True
        assert observer._frames == []
        assert observer._loop_task is None

    @pytest.mark.asyncio
    async def test_typed_queries_read_frames(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 3, "watchdogMs": 0}
        )
        await observer.start()
        observation = await observer.stop()
        captured: Dict[str, Any] = {}
        payload = {"Boolean": True, "Number": 7, "String": "seven"}

        async def fake_extract(**kwargs):
            captured.update(kwargs)
            demand_type = next(iter(kwargs["data_query"]))
            return {
                "parse_result": {"data": {demand_type: payload[demand_type]}},
                "usage": None,
            }

        with patch(
            "midscene.core.ai_model.workflows.ai_extract_element_info",
            new=AsyncMock(side_effect=fake_extract),
        ):
            assert await observation.ai_boolean("a toast appeared") is True
            assert await observation.ai_number("the item count") == 7
            assert await observation.ai_string("the item count") == "seven"
            assert await observation.ai_ask("what happened") == "seven"

        assert captured["screenshot_sequence"] == observation._frames
        assert captured["context"].screenshot_sequence == observation._frames
        await observation.dispose()

    @pytest.mark.asyncio
    async def test_typed_query_falls_back_to_result_key(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 3, "watchdogMs": 0}
        )
        await observer.start()
        observation = await observer.stop()

        async def fake_extract(**kwargs):
            return {"parse_result": {"data": {"result": 42}}, "usage": None}

        with patch(
            "midscene.core.ai_model.workflows.ai_extract_element_info",
            new=AsyncMock(side_effect=fake_extract),
        ):
            # upstream createTypeQueryTask accepts a bare `result` key
            assert await observation.ai_number("the item count") == 42
        await observation.dispose()

    @pytest.mark.asyncio
    async def test_ai_query_reads_frames(self, mock_interface):
        agent = _agent()
        observer = agent.start_observing(
            {"intervalMs": 200, "maxFrames": 3, "watchdogMs": 0}
        )
        await observer.start()
        observation = await observer.stop()
        captured: Dict[str, Any] = {}

        async def fake_extract(**kwargs):
            captured.update(kwargs)
            return {"parse_result": {"data": {"count": 3}, "thought": ""}, "usage": None}

        with patch(
            "midscene.core.ai_model.workflows.ai_extract_element_info",
            new=AsyncMock(side_effect=fake_extract),
        ):
            result = await observation.ai_query({"count": "items in the cart"})
        assert result == {"count": 3}
        assert captured["screenshot_sequence"] == observation._frames
        await observation.dispose()

    def test_start_observing_rejects_frozen_context(self, mock_interface):
        agent = _agent()
        agent._frozen = True
        with pytest.raises(RuntimeError) as exc:
            agent.start_observing()
        assert "frozen" in str(exc.value)
