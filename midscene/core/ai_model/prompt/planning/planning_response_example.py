"""Planning response examples (upstream prompt/planning/planning-response-example.ts)."""

from typing import Any


def build_planning_response_example(
    prefix: str | None = None,
    planning: str | None = None,
    update_sub_goals: list[dict[str, Any]] | None = None,
    mark_sub_goals_done: list[int] | None = None,
    memory: str | None = None,
    complete: dict[str, Any] | None = None,
    log: str | None = None,
    action_output_example: str | None = None,
) -> str:
    sections: list[str] = []
    if prefix:
        sections.append(prefix)

    if planning:
        sections.append(f"<planning>{planning}</planning>")

    if update_sub_goals:
        lines = "\n".join(
            f'  <sub-goal index="{goal["index"]}" status="{goal["status"]}">'
            f"{goal['description']}</sub-goal>"
            for goal in update_sub_goals
        )
        sections.append(f"<update-plan-content>\n{lines}\n</update-plan-content>")

    if mark_sub_goals_done:
        lines = "\n".join(
            f'  <sub-goal index="{index}" status="finished" />'
            for index in mark_sub_goals_done
        )
        sections.append(f"<mark-sub-goal-done>\n{lines}\n</mark-sub-goal-done>")

    if memory:
        sections.append(f"<memory>{memory}</memory>")

    if complete:
        sections.append(
            f'<complete success="{str(complete["success"]).lower()}">'
            f"{complete.get('message', '')}</complete>"
        )
    else:
        if not action_output_example:
            raise ValueError(
                "Cannot build planning response example without an action output example"
            )
        if log:
            sections.append(f"<log>{log}</log>")
        sections.append(action_output_example)

    return "\n".join(sections)


__all__ = ["build_planning_response_example"]
