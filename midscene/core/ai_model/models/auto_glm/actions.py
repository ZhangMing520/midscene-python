"""AutoGLM action transformation (upstream ai-model/models/auto-glm/actions.ts)."""

from collections.abc import Callable
from typing import Any

BACK_BUTTON_NAMES = ["AndroidBackButton", "HarmonyBackButton"]
HOME_BUTTON_NAMES = ["AndroidHomeButton", "HarmonyHomeButton"]


def _find_action_name(
    action_space: list[Any], known_names: list[str], default_name: str
) -> str:
    if not action_space:
        return default_name
    for action in action_space:
        name = action["name"] if isinstance(action, dict) else action.name
        if isinstance(name, str) and name in known_names:
            return name
    return default_name


def transform_auto_glm_action(
    action: dict[str, Any],
    action_space: list[Any],
    coordinate_distance_to_pixels: Callable[[float, str], float],
) -> list[dict[str, Any]]:
    """Map a parsed AutoGLM action to Midscene planning actions."""
    try:
        if action["_metadata"] == "finish":
            return [{"type": "Finished", "param": {}, "thought": action["message"]}]

        if action["_metadata"] != "do":
            raise ValueError(f"Unknown action metadata: {action['_metadata']}")

        think = action.get("think") or ""
        action_type = action["action"]

        if action_type == "Tap":
            return [
                {
                    "type": "Tap",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                }
            ]
        if action_type == "Double Tap":
            return [
                {
                    "type": "DoubleClick",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                }
            ]
        if action_type == "Type":
            return [{"type": "Input", "param": {"value": action["text"]}}]
        if action_type == "Swipe":
            start = action["start"]
            end = action["end"]
            delta_x = end[0] - start[0]
            delta_y = end[1] - start[1]
            abs_delta_x = abs(delta_x)
            abs_delta_y = abs(delta_y)
            if abs_delta_y > abs_delta_x:
                # Vertical scroll; direction inverted relative to finger movement.
                distance = coordinate_distance_to_pixels(delta_y, "y")
                direction = "up" if delta_y > 0 else "down"
            else:
                distance = coordinate_distance_to_pixels(delta_x, "x")
                direction = "left" if delta_x > 0 else "right"
            return [
                {
                    "type": "Scroll",
                    "param": {
                        "locate": {"point": start, "prompt": ""},
                        "distance": distance,
                        "direction": direction,
                    },
                    "thought": think,
                }
            ]
        if action_type == "Long Press":
            return [
                {
                    "type": "LongPress",
                    "param": {"locate": {"point": action["element"], "prompt": ""}},
                    "thought": think,
                }
            ]
        if action_type == "Back":
            return [
                {
                    "type": _find_action_name(
                        action_space, BACK_BUTTON_NAMES, "AndroidBackButton"
                    ),
                    "param": {},
                    "thought": think,
                }
            ]
        if action_type == "Home":
            return [
                {
                    "type": _find_action_name(
                        action_space, HOME_BUTTON_NAMES, "AndroidHomeButton"
                    ),
                    "param": {},
                    "thought": think,
                }
            ]
        if action_type == "Wait":
            return [
                {
                    "type": "Sleep",
                    "param": {"timeMs": action["durationMs"]},
                    "thought": think,
                }
            ]
        if action_type == "Launch":
            return [
                {"type": "Launch", "param": {"uri": action["app"]}, "thought": think}
            ]
        if action_type == "Interact":
            raise ValueError(
                'Action "Interact" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Call_API":
            raise ValueError(
                'Action "Call_API" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Take_over":
            raise ValueError(
                'Action "Take_over" from auto-glm is not supported in the current implementation.'
            )
        if action_type == "Note":
            raise ValueError(
                'Action "Note" from auto-glm is not supported in the current implementation.'
            )
        raise ValueError(f"Unknown do() action type: {action_type}")
    except ValueError as e:
        raise ValueError(f"Failed to transform action: {e}") from e


__all__ = ["transform_auto_glm_action"]
