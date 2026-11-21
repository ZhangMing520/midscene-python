"""Declarative "force a default option on every tool call" behaviors.

Port of upstream agent-tools/tool-defaults.ts. Adding a behavior flag is a
one-row change to ``TOOL_BEHAVIOR_FLAGS``.
"""

from typing import Any, Callable, Dict, List, Tuple

from midscene.shared.agent_tools.types import ToolDefaults

TOOL_BEHAVIOR_FLAGS: List[Dict[str, Any]] = [
    {
        "cli": "deep-locate",
        "description": (
            "Force deep locate for every locating operation (better precision "
            "for small/ambiguous targets, a bit slower)."
        ),
        "defaults": {"locate": {"deepLocate": True}, "act": {"deepLocate": True}},
    },
    {
        "cli": "deep-think",
        "description": (
            "Plan the act tool with deep thinking (richer context and sub-goal "
            "decomposition, a bit slower)."
        ),
        "defaults": {"act": {"deepThink": True}},
    },
]


def merge_tool_defaults(a: ToolDefaults, b: ToolDefaults) -> ToolDefaults:
    """Merge two defaults, with ``b`` taking precedence over ``a``."""
    locate = {**(a.get("locate") or {}), **(b.get("locate") or {})}
    act = {**(a.get("act") or {}), **(b.get("act") or {})}
    result: ToolDefaults = {}
    if locate:
        result["locate"] = locate
    if act:
        result["act"] = act
    return result


def resolve_tool_defaults(is_enabled: Callable[[str], bool]) -> ToolDefaults:
    resolved: ToolDefaults = {}
    for flag in TOOL_BEHAVIOR_FLAGS:
        if is_enabled(flag["cli"]):
            resolved = merge_tool_defaults(resolved, flag["defaults"])
    return resolved


def strip_behavior_flags(argv: List[str]) -> Tuple[List[str], ToolDefaults]:
    """Split argv into resolved tool defaults and remaining args."""
    enabled = set()
    raw_args: List[str] = []
    for arg in argv:
        flag = next(
            (flag for flag in TOOL_BEHAVIOR_FLAGS if arg == f"--{flag['cli']}"),
            None,
        )
        if flag is not None:
            enabled.add(flag["cli"])
        else:
            raw_args.append(arg)
    return raw_args, resolve_tool_defaults(lambda cli: cli in enabled)


__all__ = [
    "TOOL_BEHAVIOR_FLAGS",
    "merge_tool_defaults",
    "resolve_tool_defaults",
    "strip_behavior_flags",
]
