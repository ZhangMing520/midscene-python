"""Text input strategy helpers (upstream device/input-strategy.ts)."""

import inspect
import math
import re
from typing import Any, Dict, Optional, Tuple

INPUT_STRATEGIES: Tuple[str, ...] = ("legacy", "sequential", "bulk")

# Upstream exports the tuple as ``inputStrategies``; keep the Python alias for
# callers that look the constant up by name.
input_strategies = INPUT_STRATEGIES

# Distinguishes an omitted strategy (defaults to legacy) from an explicit
# ``None`` (rejected, matching upstream ``resolveInputStrategy(null)``).
_UNSET = object()


def _field(source: Any, name: str, default: Any = None) -> Any:
    """Read a camelCase/snake_case field from a dict or an object."""
    if source is None:
        return default
    wanted = "".join(char for char in str(name).lower() if char.isalnum())
    if isinstance(source, dict):
        for key, value in source.items():
            if "".join(char for char in str(key).lower() if char.isalnum()) == wanted:
                return value
        return default
    missing = object()
    value = getattr(source, name, missing)
    if value is not missing:
        return value
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(name))
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake).lower()
    return getattr(source, snake, default)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _strategy_label(value: Any) -> str:
    """Render a value the way JavaScript ``String(value)`` does."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def input_options(param: Dict[str, Any]) -> Dict[str, Any]:
    """Typing options forwarded to the device input primitive."""
    options: Dict[str, Any] = {}
    if param.get("keyboardTypeDelay") is not None:
        options["keyboard_type_delay"] = param["keyboardTypeDelay"]
    if param.get("inputStrategy") is not None:
        options["input_strategy"] = param["inputStrategy"]
    return options


def resolve_input_strategy(
    input_strategy: Any = _UNSET,
    keyboard_type_delay: Optional[float] = None,
) -> str:
    """Resolve an input strategy and reject combinations whose intent conflicts.

    Mirrors upstream ``resolveInputStrategy``: the default is ``legacy``,
    unknown strategies are rejected, and ``bulk`` cannot be combined with a
    positive keystroke delay.
    """
    if keyboard_type_delay is not None and (
        not _is_finite_number(keyboard_type_delay) or keyboard_type_delay < 0
    ):
        raise ValueError("keyboardTypeDelay must be a finite non-negative number")

    resolved = "legacy" if input_strategy is _UNSET else input_strategy
    if resolved not in INPUT_STRATEGIES:
        raise ValueError(
            "inputStrategy must be one of: "
            f"{', '.join(INPUT_STRATEGIES)}; received {_strategy_label(resolved)}"
        )
    if (
        resolved == "bulk"
        and keyboard_type_delay is not None
        and keyboard_type_delay > 0
    ):
        raise ValueError(
            'inputStrategy "bulk" requires keyboardTypeDelay to be omitted or '
            'set to 0; use inputStrategy "sequential" for delayed input'
        )
    return resolved


def resolve_text_input_options(
    action_options: Any = None,
    platform_defaults: Any = None,
) -> Dict[str, Any]:
    """Resolve action-level text input options over platform-level defaults."""
    keyboard_type_delay = _field(
        action_options, "keyboardTypeDelay", _field(action_options, "keyboard_type_delay")
    )
    if keyboard_type_delay is None:
        keyboard_type_delay = _field(
            platform_defaults,
            "keyboardTypeDelay",
            _field(platform_defaults, "keyboard_type_delay"),
        )

    action_strategy = _field(action_options, "inputStrategy", _UNSET)
    if action_strategy is _UNSET:
        action_strategy = _field(
            action_options, "input_strategy", _UNSET
        )
    if action_strategy is _UNSET:
        action_strategy = _field(platform_defaults, "inputStrategy", _UNSET)
    if action_strategy is _UNSET:
        action_strategy = _field(platform_defaults, "input_strategy", _UNSET)

    input_strategy = (
        resolve_input_strategy()
        if action_strategy is _UNSET
        else resolve_input_strategy(action_strategy, keyboard_type_delay)
    )
    return {
        "input_strategy": input_strategy,
        "keyboard_type_delay": keyboard_type_delay,
    }


def should_input_sequentially(options: Any) -> bool:
    """Whether resolved options require sending Unicode code points separately."""
    strategy = _field(options, "inputStrategy", _field(options, "input_strategy"))
    delay = _field(options, "keyboardTypeDelay", _field(options, "keyboard_type_delay"))
    return strategy == "sequential" or (
        strategy == "legacy" and delay is not None and delay > 0
    )


async def send_text_sequentially(
    text: str,
    handlers: Any,
    options: Optional[Dict[str, Any]] = None,
) -> None:
    """Send text one Unicode code point at a time with one delay policy.

    ``delay_after_last`` exists only for platforms whose legacy behavior
    included a trailing delay; explicit sequential input should leave it
    disabled.
    """
    characters = list(text)
    delay_ms = _field(options, "delayMs", _field(options, "delay_ms", 0)) or 0
    delay_after_last = _field(
        options, "delayAfterLast", _field(options, "delay_after_last", False)
    )
    send_character = _field(handlers, "sendCharacter", _field(handlers, "send_character"))
    wait = _field(handlers, "wait")

    for index, character in enumerate(characters):
        result = send_character(character)
        if inspect.isawaitable(result):
            await result
        if delay_ms > 0 and (
            index < len(characters) - 1 or delay_after_last is True
        ):
            result = wait(delay_ms)
            if inspect.isawaitable(result):
                await result
