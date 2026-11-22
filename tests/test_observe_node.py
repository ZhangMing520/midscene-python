"""Synced from upstream packages/core/tests/unit-test/observe-node.test.ts.

The upstream fixture records the root-Node lifecycle order
(start -> act -> stop -> assert -> flush -> dispose). The Python
execute_observe helper calls observer.start() explicitly, so the fixture emits
the same logical events. Observation window facts mirror the upstream fixture
(4 frames, 100ms -> 900ms).
"""

from typing import List

import pytest

from midscene.core.agent.observe_node import execute_observe
from midscene.core.agent.test_runner_nodes import AgentTestRunnerNodeExecutionContext
from midscene.core.test_runner.errors import NodeExecutionError


def _context() -> AgentTestRunnerNodeExecutionContext:
    from midscene.core.types import AbortSignal

    return AgentTestRunnerNodeExecutionContext(signal=AbortSignal())


class _FakeObservation:
    frame_count = 4
    started_at = 100
    ended_at = 900

    def __init__(self, passed: bool, order: List[str]) -> None:
        self.passed = passed
        self._order = order

    async def ai_assert(self, prompt, message=None, opt=None):
        self._order.append("assert")
        return {
            "pass": self.passed,
            "thought": "visible sequence",
            "message": None if self.passed else "did not see it",
        }


class _FakeObserver:
    buffered_frame_count = 1

    def __init__(self, observation: _FakeObservation, order: List[str]) -> None:
        self.observation = observation
        self._order = order
        self.disposed = False

    async def start(self) -> None:
        self._order.append("start")

    async def stop(self):
        self._order.append("stop")
        return self.observation

    async def dispose(self) -> None:
        self._order.append("dispose")
        self.disposed = True


class _FakeAgent:
    def __init__(self, passed: bool = True, lite: bool = False) -> None:
        self.order: List[str] = []
        self.observation = _FakeObservation(passed, self.order)
        self.observer = _FakeObserver(self.observation, self.order)
        self.acted = None
        self.flushed = False
        self._lite = lite

    def start_observing(self, opt=None):
        self.start_observing_opt = opt
        return self.observer

    async def ai_act(self, prompt, opt=None) -> None:
        self.order.append("act")
        self.acted = prompt

    async def flush_report(self) -> None:
        self.order.append("flush")
        self.flushed = True


@pytest.mark.asyncio
async def test_records_a_complete_action_window_and_flushes_report_frames_before_disposal():
    agent = _FakeAgent()
    result = await execute_observe(
        agent,
        {"act": "submit", "assert": "loading appeared", "settleMs": 0},
        _context().signal,
    )
    assert result["data"]["pass"] is True
    assert result["data"]["frameCount"] == 4
    assert result["data"]["durationMs"] == 800
    assert agent.order == ["start", "act", "stop", "assert", "flush", "dispose"]
    assert agent.start_observing_opt == {"watchdogMs": 0}
    assert agent.acted == "submit"
    assert agent.flushed is True
    assert agent.observer.disposed is True


@pytest.mark.asyncio
async def test_false_assertions_fail_the_step_and_retain_assertion_evidence():
    agent = _FakeAgent(passed=False)
    with pytest.raises(NodeExecutionError) as raised:
        await execute_observe(
            agent,
            {"act": "submit", "assert": "loading appeared", "settleMs": 0},
            _context().signal,
        )
    assert raised.value.code == "NODE_EXECUTION_ERROR"
    assert raised.value.output["data"]["pass"] is False
    assert raised.value.output["data"]["frameCount"] == 4
    assert agent.observer.disposed is True
    assert agent.order.count("dispose") == 1
