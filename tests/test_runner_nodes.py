"""Synced from upstream packages/core/tests/unit-test/test-runner-nodes.test.ts.

Node input schemas in Python are plain JSON-schema dictionaries consumed by a
runtime validator owned by the workflow engine, so upstream zod parse/reject
cases are skipped with concrete reasons. Execution and forwarding cases run
against the real node definitions in ``midscene.core.agent.test_runner_nodes``
(the legacy YAML module re-exports the same executions).
"""

from typing import Any, Dict, List, Optional

import pytest

from midscene.core.agent.agent import Agent
from midscene.core.agent.test_runner_nodes import (
    COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS,
    AgentTestRunnerNodeExecutionContext,
)
from midscene.core.test_runner.errors import NodeExecutionError
from midscene.core.types import AbortSignal

_BY_NAME = {
    definition.name: definition
    for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
}


def _context(signal: Optional[AbortSignal] = None) -> AgentTestRunnerNodeExecutionContext:
    return AgentTestRunnerNodeExecutionContext(signal=signal or AbortSignal())


class _Recorder:
    """Duck-typed Agent recording every method call made by a node."""

    def __init__(self, results: Optional[Dict[str, Any]] = None) -> None:
        self.calls: List[Any] = []
        self.results = results or {}

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)

        async def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.results.get(name)

        return record


@pytest.mark.skip(
    reason="Python node input schemas are plain dicts validated by the workflow "
    "engine; there is no inputSchema.safeParse with cross-field aiWaitFor "
    "timeout/checkInterval rules"
)
def test_validates_aiwaitfor_intervals_including_defaults():
    pass


@pytest.mark.parametrize(
    "input_value",
    [
        {"target": "aiAct", "context": "Use the test account."},
        {"target": "default", "context": ""},
        {"target": "aiAssert"},
    ],
)
@pytest.mark.asyncio
async def test_forwards_setaicontext_arguments_unchanged(input_value):
    agent = _Recorder()
    await _BY_NAME["setAIContext"].execute(agent, input_value, _context())

    assert len(agent.calls) == 1
    assert agent.calls[0][1] == (input_value.get("target"), input_value.get("context"))


@pytest.mark.skip(
    reason="Python node input schemas are plain dicts without a zod parse step, "
    "so invalid setAIContext input is not rejected by the definition"
)
def test_rejects_invalid_setaicontext_input():
    pass


@pytest.mark.asyncio
async def test_forwards_sleep_through_the_reportable_agent_api_with_cancellation():
    signal = AbortSignal()
    agent = _Recorder()
    await _BY_NAME["sleep"].execute(agent, {"ms": 20}, _context(signal))

    assert agent.calls == [("sleep", (20, {"abortSignal": signal}), {})]


@pytest.mark.asyncio
async def test_does_not_dispatch_an_already_aborted_sleep():
    signal = AbortSignal()
    signal.abort(RuntimeError("Stopped sleep"))
    agent = _Recorder()

    with pytest.raises(Exception, match="Stopped sleep"):
        await _BY_NAME["sleep"].execute(agent, {"ms": 20}, _context(signal))

    assert agent.calls == []


@pytest.mark.asyncio
async def test_fails_an_assertion_even_when_keeprawresponse_returns_pass_false():
    class _AssertAgent:
        async def ai_assert(self, prompt, message=None, options=None):
            return {"pass": False, "message": "not matched"}

    with pytest.raises(NodeExecutionError) as raised:
        await _BY_NAME["aiAssert"].execute(
            _AssertAgent(),
            {"prompt": "condition", "options": {"keepRawResponse": True}},
            _context(),
        )

    assert "not matched" in str(raised.value)
    assert raised.value.output["data"]["pass"] is False


@pytest.mark.parametrize(
    "message,expected",
    [
        (
            "Assertion failed: custom message\nReason: missing toast",
            "Assertion failed: custom message\nReason: missing toast",
        ),
        (None, "custom message"),
    ],
)
@pytest.mark.asyncio
async def test_preserves_the_agent_assertion_diagnostic_and_falls_back_to_the_requested_message(
    message, expected
):
    agent = _Recorder(
        results={
            "ai_assert": {
                "pass": False,
                "thought": "missing toast",
                "message": message,
            }
        }
    )
    signal = AbortSignal()

    with pytest.raises(Exception) as raised:
        await _BY_NAME["aiAssert"].execute(
            agent,
            {"prompt": "success toast", "message": "custom message"},
            _context(signal),
        )

    assert expected in str(raised.value)
    method, args, _kwargs = agent.calls[0]
    assert method == "ai_assert"
    assert args[0] == "success toast"
    assert args[1] == "custom message"
    assert args[2]["keepRawResponse"] is True
    assert args[2]["abortSignal"] is signal


def test_exposes_the_complete_common_agent_capability_set():
    assert Agent.get_test_runner_node_definitions() is (
        COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
    )
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


def test_documents_every_common_agent_node():
    assert [
        definition.name
        for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS
        if not (definition.description or "").strip()
    ] == []


@pytest.mark.asyncio
async def test_preserves_explicit_empty_context_overrides_for_every_ai_node():
    excluded = {"aiInput", "aiKeyboardPress", "aiPinch", "aiDragAndDrop"}
    for definition in COMMON_AGENT_TEST_RUNNER_NODE_DEFINITIONS:
        if not definition.name.startswith("ai") or definition.name in excluded:
            continue
        agent = _Recorder()
        await definition.execute(
            agent,
            {"prompt": "Inspect the page", "options": {"context": ""}},
            _context(),
        )
        _method, args, _kwargs = agent.calls[0]
        options = args[2] if definition.name == "aiAssert" else args[1]
        assert options["context"] == ""


@pytest.mark.parametrize(
    "name,method,input_value,expected_args",
    [
        (
            "aiInput",
            "ai_input",
            {
                "prompt": "Amount",
                "value": 0,
                "options": {
                    "context": "",
                    "mode": "replace",
                    "inputStrategy": "bulk",
                },
            },
            (
                "Amount",
                {
                    "context": "",
                    "mode": "replace",
                    "inputStrategy": "bulk",
                    "value": 0,
                },
            ),
        ),
        (
            "aiKeyboardPress",
            "ai_keyboard_press",
            {"keyName": "Control+A", "options": {"context": ""}},
            (None, {"context": "", "keyName": "Control+A"}),
        ),
        (
            "aiScroll",
            "ai_scroll",
            {"options": {"scrollType": "scrollToBottom", "distance": None}},
            (None, {"scrollType": "scrollToBottom", "distance": None}),
        ),
        (
            "aiPinch",
            "ai_pinch",
            {"direction": "out", "options": {"context": "", "duration": 500}},
            (None, {"context": "", "duration": 500, "direction": "out"}),
        ),
        (
            "aiLongPress",
            "ai_long_press",
            {"prompt": "Card", "options": {"duration": 800}},
            ("Card", {"duration": 800}),
        ),
    ],
)
@pytest.mark.asyncio
async def test_forwards_through_its_current_agent_signature(
    name, method, input_value, expected_args
):
    agent = _Recorder()
    await _BY_NAME[name].execute(agent, input_value, _context())

    assert agent.calls[0][0] == method
    assert agent.calls[0][1] == expected_args


@pytest.mark.asyncio
async def test_passes_both_drag_targets_through_the_shared_locator_normalization():
    agent = _Recorder()
    source = {
        "prompt": "Source card",
        "images": [{"name": "card", "url": "./card.png"}],
    }

    await _BY_NAME["aiDragAndDrop"].execute(
        agent,
        {
            "from": source,
            "to": "Destination column",
            "options": {"context": "", "deepLocate": True},
        },
        _context(),
    )

    _method, args, _kwargs = agent.calls[0]
    assert args[0] == "DragAndDrop"
    assert args[1]["from"]["prompt"] == source
    assert args[1]["from"]["deepLocate"] is True
    assert args[1]["to"]["prompt"] == "Destination column"
    assert args[1]["to"]["deepLocate"] is True


@pytest.mark.asyncio
async def test_returns_query_and_javascript_values_without_coercing_false_or_structured_data():
    signal = AbortSignal()
    prompt = {"total": "The basket total"}
    query_agent = _Recorder(results={"ai_query": {"total": 0}})
    assert await _BY_NAME["aiQuery"].execute(
        query_agent, {"prompt": prompt}, _context(signal)
    ) == {"data": {"total": 0}}
    _method, args, _kwargs = query_agent.calls[0]
    assert args[0] == prompt
    assert args[1]["abortSignal"] is signal

    script_agent = _Recorder(results={"evaluate_javascript": False})
    assert await _BY_NAME["javascript"].execute(
        script_agent, {"script": "window.isReady"}, _context(signal)
    ) == {"data": False}
    assert script_agent.calls[0][0] == "evaluate_javascript"
    assert script_agent.calls[0][1] == ("window.isReady",)


@pytest.mark.asyncio
async def test_forwards_cancellation_and_timing_options_to_wait_and_gherkin_calls():
    signal = AbortSignal()
    wait_agent = _Recorder()
    await _BY_NAME["aiWaitFor"].execute(
        wait_agent,
        {"prompt": "Ready", "options": {"timeoutMs": 100, "checkIntervalMs": 10}},
        _context(signal),
    )
    _method, args, _kwargs = wait_agent.calls[0]
    assert args[0] == "Ready"
    assert args[1] == {"timeoutMs": 100, "checkIntervalMs": 10, "abortSignal": signal}

    gherkin_agent = _Recorder()
    scenario = "Given I open the page\nThen it is ready"
    await _BY_NAME["runGherkinScenario"].execute(
        gherkin_agent,
        {"scenario": scenario, "options": {"context": ""}},
        _context(signal),
    )
    _method, args, _kwargs = gherkin_agent.calls[0]
    assert args[0] == scenario
    assert args[1] == {"context": "", "abortSignal": signal}


@pytest.mark.asyncio
async def test_defers_custom_action_validation_to_the_executing_actionspace():
    class _ActionAgent:
        def __init__(self) -> None:
            self.calls: List[Any] = []
            self.error: Optional[Exception] = None

        async def _call_action_in_action_space(self, name, params=None):
            self.calls.append((name, params))
            if self.error is not None:
                raise self.error
            if name == "CustomPlatformAction":
                return {"customResult": False}
            return None

        def get_action_space(self):
            raise AssertionError("getActionSpace must not be consulted")

    agent = _ActionAgent()
    input_value = {
        "name": "CustomPlatformAction",
        "params": {"platformSpecific": 42},
    }
    context = _context()

    assert await _BY_NAME["action"].execute(agent, input_value, context) == {
        "data": {"customResult": False}
    }
    assert agent.calls == [("CustomPlatformAction", {"platformSpecific": 42})]

    await _BY_NAME["action"].execute(
        agent,
        {"name": "CustomStringAction", "params": "text"},
        context,
    )
    assert agent.calls[-1] == ("CustomStringAction", "text")

    agent.error = ValueError("Invalid parameters for action CustomPlatformAction")
    with pytest.raises(ValueError, match="Invalid parameters for action CustomPlatformAction"):
        await _BY_NAME["action"].execute(agent, input_value, context)


@pytest.mark.asyncio
async def test_rejects_a_missing_optional_capability_only_when_its_node_executes():
    with pytest.raises(TypeError, match=r"with ai_input\(\)"):
        await _BY_NAME["aiInput"].execute(
            {}, {"prompt": "Amount", "value": ""}, _context()
        )


@pytest.mark.skip(
    reason="Python node input schemas are plain dicts; no zod parse step enforces "
    "the nested prompt/options oneOf or rejects top-level images"
)
def test_keeps_multimodal_prompts_and_method_options_nested():
    pass
