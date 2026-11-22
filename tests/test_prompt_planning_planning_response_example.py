"""Synced from upstream packages/core/tests/unit-test/prompt/planning/planning-response-example.test.ts."""

import pytest

from midscene.core.ai_model.prompt.planning.planning_response_example import (
    build_planning_response_example,
)


def test_builds_a_planning_response_with_sub_goal_state_and_an_action():
    """builds a planning response with sub-goal state and an action"""
    assert build_planning_response_example(
        planning="Continue filling the registration form.",
        update_sub_goals=[
            {
                "index": 1,
                "status": "finished",
                "description": "Fill the Name field",
            },
            {
                "index": 2,
                "status": "pending",
                "description": "Fill the Email field",
            },
        ],
        mark_sub_goals_done=[1],
        memory="The Name field contains John.",
        log="Type the email address",
        action_output_example=(
            "<action-type>Input</action-type>\n"
            "<action-param-json>\n"
            "{\n"
            '  "value": "john@example.com"\n'
            "}\n"
            "</action-param-json>"
        ),
    ) == (
        "<planning>Continue filling the registration form.</planning>\n"
        "<update-plan-content>\n"
        '  <sub-goal index="1" status="finished">Fill the Name field</sub-goal>\n'
        '  <sub-goal index="2" status="pending">Fill the Email field</sub-goal>\n'
        "</update-plan-content>\n"
        "<mark-sub-goal-done>\n"
        '  <sub-goal index="1" status="finished" />\n'
        "</mark-sub-goal-done>\n"
        "<memory>The Name field contains John.</memory>\n"
        "<log>Type the email address</log>\n"
        "<action-type>Input</action-type>\n"
        "<action-param-json>\n"
        "{\n"
        '  "value": "john@example.com"\n'
        "}\n"
        "</action-param-json>"
    )


def test_builds_a_terminal_planning_response():
    """builds a terminal planning response"""
    assert build_planning_response_example(
        planning="The task is complete.",
        mark_sub_goals_done=[2, 3],
        complete={
            "success": True,
            "message": "john@example.com",
        },
    ) == (
        "<planning>The task is complete.</planning>\n"
        "<mark-sub-goal-done>\n"
        '  <sub-goal index="2" status="finished" />\n'
        '  <sub-goal index="3" status="finished" />\n'
        "</mark-sub-goal-done>\n"
        '<complete success="true">john@example.com</complete>'
    )


def test_prepends_a_response_prefix():
    """prepends a response prefix"""
    assert build_planning_response_example(
        prefix="<response-prefix>reasoning</response-prefix>",
        planning="Continue the task.",
        action_output_example="<custom-action />",
    ) == (
        "<response-prefix>reasoning</response-prefix>\n"
        "<planning>Continue the task.</planning>\n"
        "<custom-action />"
    )


def test_throws_when_no_action_output_example_is_provided():
    """throws when no action output example is provided"""
    with pytest.raises(
        ValueError,
        match=(
            "Cannot build planning response example without an action output "
            "example"
        ),
    ):
        build_planning_response_example(
            planning="Run an action.",
            log="Run the action",
            action_output_example=None,
        )
