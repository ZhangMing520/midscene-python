"""Text input option mapping (upstream device/input-strategy.ts)."""

from typing import Any, Dict


def input_options(param: Dict[str, Any]) -> Dict[str, Any]:
    """Typing options forwarded to the device input primitive."""
    options: Dict[str, Any] = {}
    if param.get("keyboardTypeDelay") is not None:
        options["keyboard_type_delay"] = param["keyboardTypeDelay"]
    if param.get("inputStrategy") is not None:
        options["input_strategy"] = param["inputStrategy"]
    return options
