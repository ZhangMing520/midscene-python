"""Synced from upstream packages/core/tests/unit-test/run-gherkin-scenario.test.ts.

The upstream suite stubs Agent.aiAct/aiAssert on an object created from
Agent.prototype. The Python runner operates on a real Agent whose ai_act /
ai_assert methods are replaced per test; the assertions follow the upstream
case descriptions. The upstream option-forwarding case asserts an `abortSignal`
key on aiAssert options; the Python runner only forwards `context`, so that
assertion is reconciled in the empty-context case below.
"""

from unittest.mock import patch

import pytest

from tests.core_helpers import MockInterface


def _agent(**options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions

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


@pytest.mark.asyncio
async def test_runs_an_anonymous_gherkin_scenario_through_ai_act_and_ai_assert():
    agent = _agent()
    act_calls: list[tuple] = []
    assert_calls: list[tuple] = []

    async def fake_act(prompt, opt=None):
        act_calls.append((prompt, opt))

    async def fake_assert(assertion, msg=None, opt=None):
        assert_calls.append((assertion, msg, opt))

    with (
        patch.object(agent, "ai_act", new=fake_act),
        patch.object(agent, "ai_assert", new=fake_assert),
    ):
        result = await agent.run_gherkin_scenario(
            """
Given the checkout page is open
And the cart is empty
When I add "Buy milk" to the cart
Then the cart should contain "Buy milk"
And the cart total should be visible
"""
        )
    assert result is None

    assert [call[0] for call in act_calls] == [
        "Set up this precondition: the checkout page is open",
        "Set up this precondition: the cart is empty",
        'Perform this user action: I add "Buy milk" to the cart',
    ]
    assert all(call[1] == {"cacheable": False} for call in act_calls)
    assert [call[0] for call in assert_calls] == [
        'Verify that the cart should contain "Buy milk"',
        "Verify that the cart total should be visible",
    ]
    assert all(call[1] is None and call[2] is None for call in assert_calls)


@pytest.mark.asyncio
async def test_forwards_an_empty_context_to_every_gherkin_step():
    from midscene.core.agent.run_gherkin_scenario import parse_gherkin_scenario

    agent = _agent()
    act_calls: list[tuple] = []
    assert_calls: list[tuple] = []

    async def fake_act(prompt, opt=None):
        act_calls.append((prompt, opt))

    async def fake_assert(assertion, msg=None, opt=None):
        assert_calls.append((assertion, msg, opt))

    with (
        patch.object(agent, "ai_act", new=fake_act),
        patch.object(agent, "ai_assert", new=fake_assert),
    ):
        await agent.run_gherkin_scenario(
            """
Given the todo app is open
When I add "Buy milk"
Then the list should contain "Buy milk"
""",
            {"context": ""},
        )

    assert act_calls[0] == (
        "Set up this precondition: the todo app is open",
        {"context": "", "cacheable": False},
    )
    assert act_calls[1] == (
        'Perform this user action: I add "Buy milk"',
        {"context": "", "cacheable": False},
    )
    # Python forwards only context to aiAssert (no abortSignal key).
    assert assert_calls == [
        ('Verify that the list should contain "Buy milk"', None, {"context": ""})
    ]
    parsed = parse_gherkin_scenario(
        "Scenario: flow\nGiven a page\nWhen I act\nAnd I act again\nThen done"
    )
    assert [
        (step["keyword"], step["effective_keyword"]) for step in parsed["steps"]
    ] == [
        ("Given", "Given"),
        ("When", "When"),
        ("And", "When"),
        ("Then", "Then"),
    ]


@pytest.mark.asyncio
async def test_always_disables_ai_act_cache_inside_a_gherkin_scenario():
    agent = _agent()
    act_calls: list[tuple] = []

    async def fake_act(prompt, opt=None):
        act_calls.append((prompt, opt))

    with patch.object(agent, "ai_act", new=fake_act):
        await agent.run_gherkin_scenario(
            """
Given the todo app is open
When I add "Buy milk"
""",
            {"cacheable": True},
        )

    assert act_calls == [
        ("Set up this precondition: the todo app is open", {"cacheable": False}),
        ('Perform this user action: I add "Buy milk"', {"cacheable": False}),
    ]


@pytest.mark.asyncio
async def test_supports_one_scenario():
    from midscene.core.agent.run_gherkin_scenario import parse_gherkin_scenario

    agent = _agent()
    act_calls: list[str] = []
    assert_calls: list[str] = []

    async def fake_act(prompt, opt=None):
        act_calls.append(prompt)

    async def fake_assert(assertion, msg=None, opt=None):
        assert_calls.append(assertion)

    scenario = """
Scenario: Add a todo item
  Given the todo app is open
  When I add "Buy milk"
  Then the list should contain "Buy milk"
"""
    parsed = parse_gherkin_scenario(scenario)
    assert [step["text"] for step in parsed["steps"]] == [
        "the todo app is open",
        'I add "Buy milk"',
        'the list should contain "Buy milk"',
    ]
    with (
        patch.object(agent, "ai_act", new=fake_act),
        patch.object(agent, "ai_assert", new=fake_assert),
    ):
        await agent.run_gherkin_scenario(scenario)
    assert len(act_calls) == 2
    assert len(assert_calls) == 1


def test_throws_when_the_input_contains_feature():
    from midscene.core.agent.run_gherkin_scenario import parse_gherkin_scenario

    with pytest.raises(ValueError) as exc:
        parse_gherkin_scenario(
            """
Feature: Todo

Scenario: Add
  Given the todo app is open
"""
        )
    assert "does not support" in str(exc.value)
    assert "Feature: Todo" in str(exc.value)


def test_throws_when_and_or_but_has_no_previous_primary_keyword():
    from midscene.core.agent.run_gherkin_scenario import parse_gherkin_scenario

    with pytest.raises(ValueError) as exc:
        parse_gherkin_scenario("And something else")
    assert "cannot resolve" in str(exc.value)


def test_throws_when_the_input_contains_multiple_scenarios():
    from midscene.core.agent.run_gherkin_scenario import parse_gherkin_scenario

    with pytest.raises(ValueError) as exc:
        parse_gherkin_scenario(
            """
Scenario: Add
  Given the todo app is open

Scenario: Delete
  Given the todo app is open
"""
        )
    assert "exactly one Scenario" in str(exc.value)


@pytest.mark.asyncio
async def test_wraps_step_execution_errors_with_semantic_action_line_and_step_context():
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
async def test_reports_inherited_and_or_but_semantics_in_execution_errors():
    agent = _agent()

    async def fake_act(prompt, opt=None):
        if "a dialog" in prompt:
            raise RuntimeError("boom")

    with patch.object(agent, "ai_act", new=fake_act):
        with pytest.raises(RuntimeError) as exc:
            await agent.run_gherkin_scenario(
                "Scenario: flow\n  Given a page\n  And a dialog"
            )
    assert "setting up the precondition (And as Given -> aiAct) at line 3" in str(
        exc.value
    )
