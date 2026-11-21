"""Agent-level AI context keys (upstream agent-tools/agent-context.ts)."""

from typing import Any, List

AI_API_NAMES: List[str] = [
    "aiAct",
    "aiTap",
    "aiRightClick",
    "aiMiddleClick",
    "aiDoubleClick",
    "aiHover",
    "aiInput",
    "aiKeyboardPress",
    "aiScroll",
    "aiPinch",
    "aiLongPress",
    "aiClearInput",
    "aiLocate",
    "aiQuery",
    "aiBoolean",
    "aiNumber",
    "aiString",
    "aiAsk",
    "aiAssert",
    "aiWaitFor",
]

AGENT_AI_CONTEXT_KEYS: List[str] = ["default", *AI_API_NAMES]


def is_agent_ai_context_key(value: Any) -> bool:
    return isinstance(value, str) and value in AGENT_AI_CONTEXT_KEYS


__all__ = ["AGENT_AI_CONTEXT_KEYS", "AI_API_NAMES", "is_agent_ai_context_key"]
