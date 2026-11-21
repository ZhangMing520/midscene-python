"""UI-TARS action transformation (upstream ai-model/models/ui-tars/actions.ts)."""

import json
from typing import Any, Dict, List, Tuple

from loguru import logger

_UI_TARS_KEY_MAP = {
    "return": "Enter",
    "enter": "Enter",
    "command": "Meta",
    "cmd": "Meta",
    "ctrl": "Control",  # non-mac
    "shift": "Shift",
    "alt": "Alt",
    "space": " ",
    "page down": "PageDown",
    "pagedown": "PageDown",
    "page up": "PageUp",
    "pageup": "PageUp",
}


def _transform_hotkey_input(key_input: str) -> List[str]:
    lower = key_input.lower()
    if lower in _UI_TARS_KEY_MAP:
        return [_UI_TARS_KEY_MAP[lower]]
    return [
        _UI_TARS_KEY_MAP.get(token.lower(), token) for token in key_input.split(" ")
    ]


def _get_ui_tars_point(start_box: str) -> Tuple[float, float]:
    values = json.loads(start_box)
    x, y = values[0], values[1]
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ValueError(f"invalid point data for ui-tars planning: {start_box}")
    return (x, y)


def transform_ui_tars_actions(
    parsed_response: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map parsed UI-TARS actions to Midscene planning actions.
    Returns (transformed_actions, unhandled_actions)."""
    transformed: List[Dict[str, Any]] = []
    unhandled: List[Dict[str, Any]] = []

    for action in parsed_response["actions"]:
        action_type = (action.get("action_type") or "").lower()
        action_inputs = action.get("action_inputs") or {}
        thought = action.get("thought") or ""
        prompt = thought

        if action_type == "click":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "Tap",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                }
            )
        elif action_type == "left_double":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "DoubleClick",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                    "thought": thought,
                }
            )
        elif action_type == "right_single":
            if not action_inputs.get("start_box"):
                raise ValueError("start_box is required")
            point = _get_ui_tars_point(action_inputs["start_box"])
            transformed.append(
                {
                    "type": "RightClick",
                    "param": {"locate": {"point": point, "prompt": prompt}},
                    "thought": thought,
                }
            )
        elif action_type == "drag":
            if not action_inputs.get("start_box") or not action_inputs.get("end_box"):
                raise ValueError("start_box and end_box are required")
            start_point = _get_ui_tars_point(action_inputs["start_box"])
            end_point = _get_ui_tars_point(action_inputs["end_box"])
            transformed.append(
                {
                    "type": "DragAndDrop",
                    "param": {
                        "from": {"point": start_point, "prompt": prompt},
                        "to": {"point": end_point, "prompt": prompt},
                    },
                    "thought": thought,
                }
            )
        elif action_type == "type":
            transformed.append(
                {"type": "Input", "param": {"value": action_inputs.get("content")}, "thought": thought}
            )
        elif action_type == "scroll":
            transformed.append(
                {
                    "type": "Scroll",
                    "param": {"direction": action_inputs.get("direction")},
                    "thought": thought,
                }
            )
        elif action_type == "finished":
            transformed.append(
                {
                    "type": "Finished",
                    "param": {},
                    "thought": action_inputs.get("content") or thought,
                }
            )
        elif action_type == "hotkey":
            if not action_inputs.get("key"):
                logger.warning("No key found in action: hotkey. Will not perform action.")
                continue
            keys = _transform_hotkey_input(action_inputs["key"])
            transformed.append(
                {
                    "type": "KeyboardPress",
                    "param": {"keyName": "+".join(keys)},
                    "thought": thought,
                }
            )
        elif action_type == "wait":
            transformed.append(
                {"type": "Sleep", "param": {"timeMs": 1000}, "thought": thought}
            )
        elif action_type:
            unhandled.append({"type": action_type, "thought": thought})

    return transformed, unhandled


__all__ = ["transform_ui_tars_actions"]
