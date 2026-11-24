"""Sub-goals text (upstream prompt/planning/sub-goals-text.ts)."""

from typing import Any


def build_sub_goals_text(sub_goals: list[dict[str, Any]]) -> str:
    if not sub_goals:
        return ""

    lines = [
        f"{goal['index']}. {goal['description']} ({goal['status']})"
        for goal in sub_goals
    ]

    current_goal = next(
        (goal for goal in sub_goals if goal["status"] == "running"), None
    ) or next((goal for goal in sub_goals if goal["status"] == "pending"), None)

    current_goal_text = ""
    if current_goal:
        current_goal_text = f"\nCurrent sub-goal is: {current_goal['description']}"
        logs = current_goal.get("logs")
        if logs:
            log_lines = "\n".join(f"- {log}" for log in logs)
            current_goal_text += (
                f"\nActions performed for current sub-goal:\n{log_lines}"
            )

    return "Sub-goals:\n" + "\n".join(lines) + current_goal_text


__all__ = ["build_sub_goals_text"]
