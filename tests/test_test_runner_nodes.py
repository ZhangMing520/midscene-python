"""Smoke coverage for Agent / legacy YAML Test Runner node definitions."""

from typing import Any, Dict, List

import pytest

from midscene.core.agent.observe_node import execute_observe
from midscene.core.agent.test_runner_nodes import (
    COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    AgentTestRunnerNodeExecutionContext,
)
from midscene.core.test_runner.errors import NodeExecutionError
from midscene.core.yaml.test_runner_nodes import (
    LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    get_legacy_yaml_result_data,
)

_COMMON_BY_NAME = {
    definition.name: definition for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}
_LEGACY_BY_NAME = {
    definition.name: definition for definition in LEGACY_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}


def _context() -> AgentTestRunnerNodeExecutionContext:
    from midscene.core.types import AbortSignal

    return AgentTestRunnerNodeExecutionContext(signal=AbortSignal())


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: List[Any] = []
        self.assert_result: Dict[str, Any] = {"pass": True, "thought": "ok"}

    async def ai_tap(self, prompt, options=None) -> None:
        self.calls.append(("ai_tap", prompt, options))

    async def ai_assert(self, prompt, message=None, opt=None):
        self.calls.append(("ai_assert", prompt, message, opt))
        return self.assert_result

    async def ai_number(self, prompt, opt=None):
        return 42

    async def sleep(self, ms, options=None) -> None:
        self.calls.append(("sleep", ms))

    async def get_action_space(self):
        return []

    async def _call_action_in_action_space(self, name, params=None):
        self.calls.append(("action", name, dict(params or {})))
        return {"ok": True}

    async def record_to_report(self, title=None, opt=None) -> None:
        self.calls.append(("record", title, opt))


@pytest.mark.asyncio
async def test_common_node_names_match_upstream():
    expected = {
        "sleep",
        "observe",
        "aiAct",
        "aiTap",
        "aiAssert",
        "aiBoolean",
        "aiNumber",
        "aiString",
        "aiAsk",
        "recordToReport",
        "setAIContext",
        "aiHover",
        "aiDoubleClick",
        "aiRightClick",
        "aiMiddleClick",
        "aiClearInput",
        "aiInput",
        "aiKeyboardPress",
        "aiScroll",
        "aiPinch",
        "aiLongPress",
        "aiDragAndDrop",
        "aiLocate",
        "aiQuery",
        "aiWaitFor",
        "javascript",
        "runGherkinScenario",
        "action",
    }
    assert set(_COMMON_BY_NAME) == expected


@pytest.mark.asyncio
async def test_ai_tap_and_insight_nodes_call_agent():
    agent = _FakeAgent()
    result = await _COMMON_BY_NAME["aiTap"].execute(
        agent, {"prompt": "submit", "options": {"deepLocate": True}}, _context()
    )
    assert result == {"summary": "Tapped: submit"}
    assert agent.calls[0] == ("ai_tap", "submit", {"deepLocate": True})

    number = await _COMMON_BY_NAME["aiNumber"].execute(
        agent, {"prompt": "count", "options": {}}, _context()
    )
    assert number == {"summary": "aiNumber returned 42", "data": {"value": 42}}


@pytest.mark.asyncio
async def test_ai_assert_failure_raises_with_result():
    agent = _FakeAgent()
    agent.assert_result = {"pass": False, "thought": "not visible", "message": "nope"}
    with pytest.raises(NodeExecutionError) as raised:
        await _COMMON_BY_NAME["aiAssert"].execute(
            agent, {"prompt": "visible"}, _context()
        )
    assert raised.value.output["data"]["pass"] is False
    assert "Assertion failed: visible" in raised.value.output["summary"]


@pytest.mark.asyncio
async def test_drag_and_drop_uses_action_space():
    agent = _FakeAgent()
    await _COMMON_BY_NAME["aiDragAndDrop"].execute(
        agent, {"from": "card", "to": "column"}, _context()
    )
    name, params = agent.calls[0][1], agent.calls[0][2]
    assert name == "DragAndDrop"
    assert params["from"]["prompt"] == "card"
    assert params["to"]["prompt"] == "column"


@pytest.mark.asyncio
async def test_legacy_action_compiles_flow_item():
    agent = _FakeAgent()
    definition = _LEGACY_BY_NAME["legacyAction"]
    await definition.execute(agent, {"flow": {"aiTap": "login"}}, _context())
    assert agent.calls[0] == ("ai_tap", "login", {})


@pytest.mark.asyncio
async def test_legacy_run_adb_shell_falls_back_to_action_space():
    agent = _FakeAgent()
    result = await _LEGACY_BY_NAME["runAdbShell"].execute(
        agent, {"command": "ls", "timeout": 1000}, _context()
    )
    assert result == {"data": {"ok": True}}
    assert agent.calls[0] == ("action", "RunAdbShell", {"command": "ls", "timeout": 1000})


@pytest.mark.asyncio
async def test_legacy_validation_error_message():
    with pytest.raises(RuntimeError, match="missing flow"):
        await _LEGACY_BY_NAME["legacyValidationError"].execute(
            _FakeAgent(), {"message": "missing flow"}, _context()
        )


def test_finalize_is_a_noop():
    assert _LEGACY_BY_NAME["Finalize"].execute(_FakeAgent(), {}, _context()) is None


def test_legacy_result_data_unwraps_insights_only():
    assert get_legacy_yaml_result_data("aiNumber", {"data": {"value": 3}}) == 3
    assert get_legacy_yaml_result_data("aiLocate", {"data": {"value": 3}}) == {
        "value": 3
    }
    assert get_legacy_yaml_result_data("aiNumber", {"data": 5}) is None


class _FakeObservation:
    frame_count = 2
    started_at = 0
    ended_at = 120

    def __init__(self, passed: bool = True) -> None:
        self.passed = passed

    async def ai_assert(self, prompt, message=None, opt=None):
        return {
            "pass": self.passed,
            "thought": "saw it",
            "message": None if self.passed else "did not see it",
        }


class _FakeObserver:
    buffered_frame_count = 1

    def __init__(self, observation: _FakeObservation) -> None:
        self.observation = observation
        self.disposed = False

    async def start(self) -> None:
        return None

    async def stop(self):
        return self.observation

    async def dispose(self) -> None:
        self.disposed = True


class _FakeObserveAgent:
    def __init__(self, passed: bool = True) -> None:
        self.observation = _FakeObservation(passed)
        self.observer = _FakeObserver(self.observation)
        self.acted = None
        self.flushed = False

    def start_observing(self, opt=None):
        return self.observer

    async def ai_act(self, prompt, opt=None) -> None:
        self.acted = prompt

    async def flush_report(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_execute_observe_passes_and_reports_frames():
    agent = _FakeObserveAgent()
    result = await execute_observe(
        agent, {"act": "click", "assert": "toast", "settleMs": 0}, _context().signal
    )
    assert result["summary"] == "Observation passed: toast"
    assert result["data"]["frameCount"] == 2
    assert result["data"]["pass"] is True
    assert agent.acted == "click"
    assert agent.flushed is True
    assert agent.observer.disposed is True


@pytest.mark.asyncio
async def test_execute_observe_failure_raises_node_error():
    agent = _FakeObserveAgent(passed=False)
    with pytest.raises(NodeExecutionError) as raised:
        await execute_observe(
            agent, {"act": "click", "assert": "toast", "settleMs": 0}, _context().signal
        )
    assert raised.value.code == "NODE_EXECUTION_ERROR"
    assert raised.value.output["data"]["pass"] is False
