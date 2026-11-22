"""Synced from upstream packages/core/tests/unit-test/prompt/planning/sub-goals-text.test.ts."""

from midscene.core.ai_model.prompt.planning.sub_goals_text import (
    build_sub_goals_text,
)


def test_returns_an_empty_string_when_no_sub_goals_are_provided():
    """returns an empty string when no sub-goals are provided"""
    assert build_sub_goals_text([]) == ""


def test_renders_all_sub_goals_and_the_running_sub_goal_progress():
    """renders all sub-goals and the running sub-goal progress"""
    assert build_sub_goals_text(
        [
            {
                "index": 1,
                "status": "finished",
                "description": "Fill the Name field",
            },
            {
                "index": 2,
                "status": "running",
                "description": "Fill the Email field",
                "logs": ["Click the Email field", "Type the email address"],
            },
            {
                "index": 3,
                "status": "pending",
                "description": "Return the email address",
            },
        ]
    ) == (
        "Sub-goals:\n"
        "1. Fill the Name field (finished)\n"
        "2. Fill the Email field (running)\n"
        "3. Return the email address (pending)\n"
        "Current sub-goal is: Fill the Email field\n"
        "Actions performed for current sub-goal:\n"
        "- Click the Email field\n"
        "- Type the email address"
    )


def test_uses_the_first_pending_sub_goal_when_none_is_running():
    """uses the first pending sub-goal when none is running"""
    assert build_sub_goals_text(
        [
            {
                "index": 1,
                "status": "finished",
                "description": "Open the form",
            },
            {
                "index": 2,
                "status": "pending",
                "description": "Submit the form",
            },
        ]
    ) == (
        "Sub-goals:\n"
        "1. Open the form (finished)\n"
        "2. Submit the form (pending)\n"
        "Current sub-goal is: Submit the form"
    )
