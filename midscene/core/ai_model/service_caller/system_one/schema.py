"""System One response schema validation (upstream system-one/schema.ts)."""

import json
from typing import Any


class SystemOneError(Exception):
    pass


def validate_system_one_response(payload: Any) -> dict[str, Any]:
    """Validate a System One response (answers + usage)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise SystemOneError(
            f"invalid System One response: {json.dumps(payload)[:500]}"
        )

    for name, raw_answer in payload["answers"].items():
        if not isinstance(raw_answer, dict):
            raise SystemOneError(f"invalid System One answer: {name}")
        answer = raw_answer
        answer_type = answer.get("type")
        if answer_type == "noul":
            _validate_probability(answer.get("noul"))
        elif answer_type == "choice":
            if not isinstance(answer.get("choice"), str):
                raise SystemOneError(f"invalid System One choice answer: {name}")
        elif answer_type == "box":
            box = answer.get("box") or {}
            if not isinstance(box, dict):
                raise SystemOneError(f"invalid System One box answer: {name}")
            left, right = box.get("left"), box.get("right")
            top, bottom = box.get("top"), box.get("bottom")
            left, right, top, bottom = (
                _validate_probability(value) for value in (left, right, top, bottom)
            )
            if not (left < right and top < bottom):
                raise SystemOneError("Invalid box edges")
        else:
            raise SystemOneError(f"unknown System One answer type: {answer_type}")

    usage = payload.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise SystemOneError("invalid System One usage")
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                usage[key] = None
    return payload


def _validate_probability(value: Any) -> float:
    if not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise SystemOneError(f"invalid probability value: {value!r}")
    return value


__all__ = ["SystemOneError", "validate_system_one_response"]
