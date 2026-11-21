"""Planning conversation history (upstream workflows/planning/conversation-history.ts)."""

from typing import Any, Dict, List, Optional


class ConversationHistory:
    """Track messages, historical logs and memories across planning turns."""

    def __init__(self, images_include_count: int = 2):
        self.messages: List[Dict[str, Any]] = []
        self.historical_logs: List[str] = []
        self.memories: List[str] = []
        self.sub_goals: List[Dict[str, Any]] = []
        self.pending_feedback_message: Optional[str] = None
        self.images_include_count = images_include_count

    def append_message(self, message: Dict[str, Any]) -> None:
        self.messages.append(message)

    def append_historical_log(self, log: str) -> None:
        if log:
            self.historical_logs.append(log)

    def append_memory(self, memory: str) -> None:
        if memory:
            self.memories.append(memory)

    def reset_pending_feedback_message_if_exists(self) -> None:
        self.pending_feedback_message = None

    def historical_logs_to_text(self) -> str:
        if not self.historical_logs:
            return ""
        lines = "\n".join(f"- {log}" for log in self.historical_logs)
        return f"### Historical execution logs\n{lines}"

    def memories_to_text(self) -> str:
        if not self.memories:
            return ""
        lines = "\n".join(f"- {memory}" for memory in self.memories)
        return f"### Memories\n{lines}"

    def sub_goals_to_text(self) -> str:
        from midscene.core.ai_model.prompt.planning import build_sub_goals_text

        return build_sub_goals_text(self.sub_goals)

    def snapshot(self, images_include_count: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return recent history, keeping at most N images."""
        limit = (
            images_include_count
            if images_include_count is not None
            else self.images_include_count
        )
        result: List[Dict[str, Any]] = []
        image_count = 0
        for message in reversed(self.messages):
            content = message.get("content")
            has_image = isinstance(content, list) and any(
                part.get("type") == "image" for part in content
            )
            if has_image:
                if image_count >= limit:
                    continue
                image_count += 1
            result.append(message)
        result.reverse()
        return result

    def compress_history(self, threshold: int = 50, keep: int = 20) -> None:
        if len(self.messages) <= threshold:
            return
        self.messages = self.messages[-keep:]


__all__ = ["ConversationHistory"]
