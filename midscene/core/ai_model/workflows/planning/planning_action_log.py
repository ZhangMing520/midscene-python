"""Planning action logs (upstream workflows/planning/planning-action-log.ts)."""

from typing import Any, Dict, List


def _build_non_action_planning_log(response: Dict[str, Any]) -> str:
    if response.get("error"):
        return f"Error - {response['error']}"
    if response.get("finalize_success") is not None:
        parts = [f"Complete - success: {str(response['finalize_success']).lower()}"]
        if response.get("finalize_message"):
            parts.append(f"message: {response['finalize_message']}")
        return ", ".join(parts)
    return "No action"


def build_planning_action_log(action: Dict[str, Any], action_space: List[Any]) -> str:
    """Build a human-readable log line for an executed planning action."""
    action_dict = next(
        (
            (a if isinstance(a, dict) else a.to_prompt_dict())
            for a in action_space
            if (a if isinstance(a, dict) else a.to_prompt_dict())["name"]
            == action["type"]
        ),
        None,
    )
    param = action.get("param") or {}
    locate = param.get("locate") or {}
    target = (
        locate.get("prompt") if isinstance(locate, dict) else None
    ) or param.get("value") or param.get("keyName") or ""
    interface_alias = (action_dict or {}).get("interface_alias")
    return f"{interface_alias or action['type']}({target})"


__all__ = ["build_planning_action_log"]
