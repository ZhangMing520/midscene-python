"""Synced from upstream packages/core/tests/unit-test/test-runner-nodes.test.ts.

The upstream suite creates definitions through zod schemas; Python node
definitions carry plain dict schemas, so schema-validation cases have no
Python counterpart and are not synced here. The remaining cases keep the
upstream case names and assertions.
"""

from typing import Any, List

import pytest

from midscene.core.agent.test_runner_nodes import (
    COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    AgentTestRunnerNodeExecutionContext,
)
from midscene.core.test_runner.errors import NodeExecutionError

_BY_NAME = {
    definition.name: definition for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}


def _context() -> AgentTestRunnerNodeExecutionContext:
    from midscene.core.types import AbortSignal

    return AgentTestRunnerNodeExecutionContext(signal=AbortSignal())


class _FakeAgent:
    def __init__(self) -> None:
        self.calls: List[Any] = []

    async def ai_assert(self, prompt, message=None, opt=None):
        self.calls.append(("ai_assert", prompt, message, opt))
        return {"pass": False, "message": "not matched"}

    async def _call_action_in_action_space(self, name, params=None):
        self.calls.append(("action", name, params))
        return None


def test_exposes_the_complete_common_agent_capability_set():
    assert [
        (definition.name, definition.string_input_key)
        for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
    ] == [
        ("sleep", None),
        ("observe", False),
        ("aiAct", "prompt"),
        ("aiTap", "prompt"),
        ("aiAssert", "prompt"),
        ("aiBoolean", "prompt"),
        ("aiNumber", "prompt"),
        ("aiString", "prompt"),
        ("aiAsk", "prompt"),
        ("recordToReport", "title"),
        ("setAIContext", None),
        ("aiHover", "prompt"),
        ("aiDoubleClick", "prompt"),
        ("aiRightClick", "prompt"),
        ("aiMiddleClick", "prompt"),
        ("aiClearInput", "prompt"),
        ("aiInput", None),
        ("aiKeyboardPress", "keyName"),
        ("aiScroll", "prompt"),
        ("aiPinch", None),
        ("aiLongPress", "prompt"),
        ("aiDragAndDrop", None),
        ("aiLocate", "prompt"),
        ("aiQuery", "prompt"),
        ("aiWaitFor", "prompt"),
        ("javascript", "script"),
        ("runGherkinScenario", "scenario"),
        ("action", None),
    ]


@pytest.mark.asyncio
async def test_fails_an_assertion_even_when_keeprawresponse_returns_pass_false():
    agent = _FakeAgent()
    with pytest.raises(NodeExecutionError) as raised:
        await _BY_NAME["aiAssert"].execute(
            agent,
            {"prompt": "condition", "options": {"keepRawResponse": True}},
            _context(),
        )
    assert "not matched" in str(raised.value)
    assert raised.value.output["data"]["pass"] is False


@pytest.mark.asyncio
async def test_passes_both_drag_targets_through_the_shared_locator_normalization():
    agent = _FakeAgent()
    source = {"prompt": "Source card", "images": [{"name": "card", "url": "./card.png"}]}
    await _BY_NAME["aiDragAndDrop"].execute(
        agent,
        {
            "from": source,
            "to": "Destination column",
            "options": {"context": "", "deepLocate": True},
        },
        _context(),
    )
    name, params = agent.calls[0][1], agent.calls[0][2]
    assert name == "DragAndDrop"
    assert params["from"]["prompt"] == source
    assert params["from"]["deepLocate"] is True
    assert params["to"]["prompt"] == "Destination column"
    assert params["to"]["deepLocate"] is True
