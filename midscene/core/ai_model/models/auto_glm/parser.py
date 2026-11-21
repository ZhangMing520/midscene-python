"""AutoGLM response parsing (upstream ai-model/models/auto-glm/parser.ts)."""

import re
from typing import Any, Dict, Tuple


def _extract_value_after(src: str, key: str) -> str:
    """Substring-based value extraction; regex breaks on escaped quotes."""
    idx = src.find(key)
    if idx == -1:
        raise ValueError(f"Missing key {key} in action payload {src}")
    rest = src[idx + len(key):].strip()
    if rest.endswith('")'):
        rest = rest[:-2]
    return rest


def parse_auto_glm_response(content: str) -> Dict[str, str]:
    """Split a raw response into {think, content}."""
    if "finish(message=" in content:
        parts = content.split("finish(message=")
        return {"think": parts[0].strip(), "content": f"finish(message={parts[1]}"}
    if "do(action=" in content:
        parts = content.split("do(action=")
        return {"think": parts[0].strip(), "content": f"do(action={parts[1]}"}
    if "<answer>" in content:
        parts = content.split("<answer>")
        think = parts[0].replace("<think>", "").replace("</think>", "").strip()
        return {"think": think, "content": parts[1].replace("</answer>", "").strip()}
    return {"think": "", "content": content}


def parse_auto_glm_planning_action(response: Dict[str, str]) -> Dict[str, Any]:
    """Parse the AutoGLM action payload into a discriminated dict."""
    think = response.get("think", "")
    trimmed = response["content"].strip()
    try:
        if trimmed.startswith('do(action="Type"') or trimmed.startswith('do(action="Type_Name"'):
            text = _extract_value_after(trimmed, 'text="')
            return {"_metadata": "do", "action": "Type", "text": text, "think": think}

        if trimmed.startswith("finish(message="):
            message = _extract_value_after(trimmed, 'finish(message="')
            if not trimmed.endswith('")') and message.endswith(")"):
                message = message[:-1]
            return {"_metadata": "finish", "message": message, "think": think}

        if trimmed.startswith("do("):
            action_match = re.search(r'do\(action="([^"]+)"', trimmed)
            if not action_match:
                raise ValueError(
                    f"Failed to extract action type from do() call; raw=\"{trimmed}\""
                )
            action_type = action_match.group(1)
            base: Dict[str, Any] = {"_metadata": "do", "think": think}

            def _coords(pattern: str, label: str) -> Tuple[int, int]:
                match = re.search(pattern, trimmed)
                if not match:
                    raise ValueError(
                        f"Failed to extract {label} coordinates for {action_type}; "
                        f"raw=\"{trimmed}\""
                    )
                return (int(match.group(1)), int(match.group(2)))

            if action_type == "Tap":
                base["action"] = "Tap"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Double Tap":
                base["action"] = "Double Tap"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Swipe":
                base["action"] = "Swipe"
                base["start"] = _coords(r"start=\[(\d+),(\d+)\]", "start")
                base["end"] = _coords(r"end=\[(\d+),(\d+)\]", "end")
                return base
            if action_type == "Long Press":
                base["action"] = "Long Press"
                base["element"] = _coords(r"element=\[(\d+),(\d+)\]", "element")
                return base
            if action_type == "Launch":
                base["action"] = "Launch"
                base["app"] = _extract_value_after(trimmed, 'app="')
                return base
            if action_type == "Back":
                base["action"] = "Back"
                return base
            if action_type == "Home":
                base["action"] = "Home"
                return base
            if action_type == "Wait":
                base["action"] = "Wait"
                match = re.search(r'duration=(?:["\[])?(\d+)', trimmed)
                if not match:
                    raise ValueError(
                        f"Failed to extract duration for Wait; raw=\"{trimmed}\""
                    )
                base["durationMs"] = int(match.group(1)) * 1000
                return base
            if action_type == "Interact":
                base["action"] = "Interact"
                return base
            if action_type == "Call_API":
                base["action"] = "Call_API"
                base["instruction"] = _extract_value_after(trimmed, 'instruction="')
                return base
            if action_type == "Take_over":
                base["action"] = "Take_over"
                base["message"] = _extract_value_after(trimmed, 'message="')
                return base
            if action_type == "Note":
                base["action"] = "Note"
                base["message"] = _extract_value_after(trimmed, 'message="')
                return base
            raise ValueError(f"Unknown action type: {action_type}; raw=\"{trimmed}\"")

        raise ValueError(f"Failed to parse action: {trimmed}")
    except ValueError as e:
        raise ValueError(f"Failed to parse action: {e}; raw=\"{trimmed}\"") from e


def parse_auto_glm_planning_response(content: str) -> Dict[str, Any]:
    response = parse_auto_glm_response(content)
    return {
        "response": response,
        "action": parse_auto_glm_planning_action(response),
    }


__all__ = [
    "parse_auto_glm_planning_action",
    "parse_auto_glm_planning_response",
    "parse_auto_glm_response",
]
