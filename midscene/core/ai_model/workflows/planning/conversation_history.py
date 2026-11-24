"""Planning conversation history (upstream workflows/planning/conversation-history.ts)."""

import copy
from collections.abc import Iterator
from typing import Any


class ConversationHistory:
    """Track messages, sub-goals, historical logs and memories across turns."""

    def __init__(
        self,
        initial_messages: list[dict[str, Any]] | None = None,
        images_include_count: int = 2,
    ):
        self._messages: list[dict[str, Any]] = []
        self.sub_goals: list[dict[str, Any]] = []
        self.memories: list[str] = []
        self.historical_logs: list[str] = []
        self.pending_feedback_message: str = ""
        self.images_include_count = images_include_count
        if initial_messages:
            self.seed(initial_messages)

    # -- messages ---------------------------------------------------------

    def append_message(self, message: dict[str, Any]) -> None:
        self._messages.append({"type": "input-message", "message": message})

    def append_model_output(self, output: dict[str, Any]) -> None:
        self._messages.append({"type": "model-output", "output": output})

    def seed(self, messages: list[dict[str, Any]]) -> None:
        self.reset()
        self._messages.extend(messages)

    def reset(self) -> None:
        self._messages.clear()
        self.memories.clear()
        self.sub_goals.clear()
        self.historical_logs.clear()
        self.pending_feedback_message = ""

    def snapshot(self, max_images: int | None = None) -> list[dict[str, Any]]:
        """Return history entries, replacing images beyond ``max_images``.

        ``None`` means no limit. When a limit is given, the most recent images
        are kept and older ones become text placeholders.
        """
        if max_images is None:
            return list(self._messages)

        cloned_messages = copy.deepcopy(self._messages)
        image_count = 0
        for entry in reversed(cloned_messages):
            if entry.get("type") != "input-message":
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for index, item in enumerate(content):
                if isinstance(item, dict) and item.get("type") == "image":
                    image_count += 1
                    if image_count > max_images:
                        content[index] = {
                            "type": "text",
                            "text": "(image ignored due to size optimization)",
                        }
        return cloned_messages

    @property
    def length(self) -> int:
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._messages)

    def to_json(self) -> list[dict[str, Any]]:
        return self.snapshot()

    def reset_pending_feedback_message_if_exists(self) -> None:
        if self.pending_feedback_message:
            self.pending_feedback_message = ""

    # -- sub-goals --------------------------------------------------------

    def set_sub_goals(self, sub_goals: list[dict[str, Any]]) -> None:
        self.sub_goals = [dict(goal) for goal in sub_goals]
        self.mark_first_pending_as_running()

    def merge_sub_goals(self, sub_goals: list[dict[str, Any]]) -> None:
        if not self.sub_goals:
            self.set_sub_goals(sub_goals)
            return

        existing_by_index = {goal["index"]: goal for goal in self.sub_goals}
        merged: list[dict[str, Any]] = []
        for goal in sub_goals:
            existing_goal = existing_by_index.get(goal["index"])
            has_non_empty_description = bool((goal.get("description") or "").strip())

            if existing_goal is None and not has_non_empty_description:
                continue

            merged.append(
                {
                    **goal,
                    "description": (
                        goal.get("description") or ""
                        if has_non_empty_description or existing_goal is None
                        else existing_goal.get("description", "")
                    ),
                }
            )

        if not merged:
            return
        self.set_sub_goals(merged)

    def update_sub_goal(self, index: int, updates: dict[str, Any]) -> bool:
        goal = next((goal for goal in self.sub_goals if goal["index"] == index), None)
        if goal is None:
            return False

        changed = False
        if "status" in updates and updates["status"] != goal.get("status"):
            goal["status"] = updates["status"]
            changed = True
        if "description" in updates and updates["description"] != goal.get(
            "description"
        ):
            goal["description"] = updates["description"]
            changed = True

        if changed:
            goal["logs"] = []
        return True

    def mark_first_pending_as_running(self) -> None:
        first_pending = next(
            (goal for goal in self.sub_goals if goal.get("status") == "pending"),
            None,
        )
        if first_pending is not None:
            first_pending["status"] = "running"
            first_pending["logs"] = []

    def mark_sub_goal_finished(self, index: int) -> bool:
        result = self.update_sub_goal(index, {"status": "finished"})
        if result:
            self.mark_first_pending_as_running()
        return result

    def mark_all_sub_goals_finished(self) -> None:
        for goal in self.sub_goals:
            if goal.get("status") != "finished":
                goal["logs"] = []
            goal["status"] = "finished"

    def append_sub_goal_log(self, log: str) -> None:
        if not log:
            return
        running_goal = next(
            (goal for goal in self.sub_goals if goal.get("status") == "running"),
            None,
        )
        if running_goal is not None:
            running_goal.setdefault("logs", [])
            running_goal["logs"].append(log)

    def sub_goals_to_text(self) -> str:
        from midscene.core.ai_model.prompt.planning import build_sub_goals_text

        return build_sub_goals_text(self.sub_goals)

    # -- historical logs --------------------------------------------------

    def append_historical_log(self, log: str) -> None:
        if log:
            self.historical_logs.append(log)

    def historical_logs_to_text(self) -> str:
        if not self.historical_logs:
            return ""
        log_lines = "\n".join(f"- {log}" for log in self.historical_logs)
        return f"Here are the steps that have been executed:\n{log_lines}"

    # -- memories ---------------------------------------------------------

    def append_memory(self, memory: str) -> None:
        if memory:
            self.memories.append(memory)

    def get_memories(self) -> list[str]:
        return list(self.memories)

    def memories_to_text(self) -> str:
        if not self.memories:
            return ""
        return (
            "Memories from previous steps:\n---\n"
            + "\n---\n".join(self.memories)
            + "\n"
        )

    def clear_memories(self) -> None:
        self.memories.clear()

    # -- compression ------------------------------------------------------

    def compress_history(self, threshold: int, keep_count: int) -> bool:
        if len(self._messages) <= threshold:
            return False

        omitted_count = len(self._messages) - keep_count
        omitted_placeholder = {
            "role": "user",
            "content": (
                f"({omitted_count} previous conversation messages have been omitted)"
            ),
        }
        recent_messages = self._messages[-keep_count:]

        self._messages.clear()
        self.append_message(omitted_placeholder)
        self._messages.extend(recent_messages)
        return True


__all__ = ["ConversationHistory"]
