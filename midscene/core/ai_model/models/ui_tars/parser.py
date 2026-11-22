"""UI-TARS response parser (upstream ai-model/models/ui-tars/parser.ts)."""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _convert_bbox_to_coordinates(text: str) -> str:
    pattern = re.compile(r"<bbox>(\d+)\s+(\d+)\s+(\d+)\s+(\d+)</bbox>")

    def replace_match(match: re.Match) -> str:
        x1, y1, x2, y2 = (int(g) for g in match.groups())
        x = (x1 + x2) // 2
        y = (y1 + y2) // 2
        return f"({x},{y})"

    cleaned = text.replace("[EOS]", "")
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_-]+)?", "", cleaned)
    return pattern.sub(replace_match, cleaned).strip()


_THOUGHT_PATTERN = re.compile(r"Thought:\s*([\s\S]*?)(?=Action:|$)", re.IGNORECASE)
_ACTION_LINE_PATTERN = re.compile(r"Action[^\n:]*:\s*([\s\S]+)", re.IGNORECASE)


def parse_ui_tars_action_calls(raw_response: str) -> List[Dict[str, Any]]:
    """Minimal port of @ui-tars/action-parser: parse 'Action: name(k=v, ...)'
    calls with factor 1000 (coordinates become [0,1] floats)."""
    converted = _convert_bbox_to_coordinates(raw_response)
    thought_match = _THOUGHT_PATTERN.search(converted)
    thought = thought_match.group(1).strip() if thought_match else None

    action_match = _ACTION_LINE_PATTERN.search(converted)
    if not action_match:
        return []
    action_text = action_match.group(1).strip()

    parsed: List[Dict[str, Any]] = []
    for action_type, inputs_text in _iter_action_calls(action_text):
        action_inputs: Dict[str, Any] = {}
        for key, value in _parse_action_kwargs(inputs_text):
            if key in ("start_box", "end_box"):
                action_inputs[key] = _normalize_box(value)
            else:
                action_inputs[key] = value
        parsed.append(
            {
                "action_type": action_type,
                "action_inputs": action_inputs,
                "reflection": None,
                "thought": thought,
            }
        )
    return parsed


def _iter_action_calls(action_text: str) -> List[Tuple[str, str]]:
    """Find `name(...)` calls with a balanced-paren scan so quoted values
    containing parentheses or nested tuples are handled."""
    calls: List[Tuple[str, str]] = []
    index = 0
    while index < len(action_text):
        open_paren = action_text.find("(", index)
        if open_paren == -1:
            break
        name_match = re.search(r"(\w+)\($", action_text[: open_paren + 1])
        if not name_match:
            index = open_paren + 1
            continue
        depth = 1
        cursor = open_paren + 1
        in_string: Optional[str] = None
        while cursor < len(action_text) and depth > 0:
            char = action_text[cursor]
            if in_string:
                if char == in_string:
                    in_string = None
            elif char in ("'", '"'):
                in_string = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        if depth != 0:
            break
        calls.append((name_match.group(1), action_text[open_paren + 1 : cursor - 1]))
        index = cursor
    return calls


def _parse_action_kwargs(inputs_text: str) -> List[Tuple[str, Any]]:
    kwargs: List[Tuple[str, Any]] = []
    for part in re.findall(r"(\w+)\s*=\s*('[^']*'|\"[^\"]*\"|\[[^\]]*\]|[^,]+)", inputs_text):
        key, raw_value = part[0], part[1].strip()
        if (raw_value.startswith("'") and raw_value.endswith("'")) or (
            raw_value.startswith('"') and raw_value.endswith('"')
        ):
            kwargs.append((key, raw_value[1:-1]))
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            kwargs.append((key, raw_value))
        else:
            kwargs.append((key, raw_value))
    return kwargs


def _normalize_box(box_text: str) -> str:
    """Replicate action-parser's factor-1000 handling: parse up to 4 numbers,
    divide by 1000, duplicate to 4, and store as a JSON string."""
    numbers = [float(n) for n in re.findall(r"-?\d+\.?\d*", str(box_text))]
    if not numbers:
        raise ValueError(f"invalid box data for ui-tars planning: {box_text}")
    float_numbers = [n / 1000 for n in numbers]
    if len(float_numbers) == 2:
        float_numbers = [float_numbers[0], float_numbers[1], float_numbers[0], float_numbers[1]]
    return json.dumps(float_numbers)


def parse_ui_tars_planning_response(
    raw_response: str,
    shot_size: Dict[str, Any],
    ui_tars_model_version: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "rawResponse": raw_response,
        "actions": parse_ui_tars_action_calls(raw_response),
        "uiTarsModelVersion": ui_tars_model_version,
    }


__all__ = ["parse_ui_tars_action_calls", "parse_ui_tars_planning_response"]
