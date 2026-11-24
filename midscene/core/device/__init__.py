"""Device action space.

Synced from upstream packages/core/src/device/index.ts (web subset) with the
param schemas pre-declared as plain dicts (upstream derives them from zod).
Each action binds to device primitives exposed by the platform interface.
"""

import asyncio
import inspect
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from midscene.core.device.device_options import (
    _accepts_keyword,
    _scroll_supported_kwargs,
    _supported_kwargs,
)
from midscene.core.device.input_strategy import input_options
from midscene.core.types import supports_interface_extension

LOCATE_PARAM = {
    "type": "{ prompt: string }",
    "description": "The element to operate on",
}


def _supports(device: Any, primitive: str) -> bool:
    """True when the concrete interface overrides the base-class stub."""
    return supports_interface_extension(device, primitive)


@dataclass
class DeviceAction:
    """One entry of the planning action space."""

    name: str
    description: str
    param_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    locate_fields: list[str] = field(default_factory=list)
    distance_fields: list[str] = field(default_factory=list)
    sample: dict[str, Any] | None = None
    interface_alias: str | None = None
    supported_by_system_one: bool = False
    primitive: str | None = None  # device method the action requires
    execute: Callable[..., Any] | None = None  # async (param, device, locate_fn)
    delay_before_runner: float | None = None
    delay_after_runner: float | None = None
    planning_feedback_max_length: Any | None = None  # int | "unlimited"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "param_schema": self.param_schema,
            "locate_fields": self.locate_fields,
            "distance_fields": self.distance_fields,
            "sample": self.sample,
            "interface_alias": self.interface_alias,
            "supported_by_system_one": self.supported_by_system_one,
        }


def find_action_in_action_space_or_throw(
    action_type: str, action_space: list[Any]
) -> Any:
    for action in action_space:
        name = action["name"] if isinstance(action, dict) else action.name
        if name == action_type:
            return action
    available = ", ".join(
        action["name"] if isinstance(action, dict) else action.name
        for action in action_space
    )
    raise ValueError(
        f"Action type '{action_type}' is not in the current action space. "
        f"Available actions: {available or '(none)'}"
    )


def scale_action_distances(
    param: dict[str, Any], definition: Any, ratio: float
) -> dict[str, Any]:
    """Convert model-input-image-pixel distances to device-logical units."""
    distance_fields = (
        definition.get("distance_fields")
        if isinstance(definition, dict)
        else definition.distance_fields
    ) or []
    if not distance_fields:
        return param

    result = dict(param or {})
    for name in distance_fields:
        value = result.get(name)
        if value is None:
            continue
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name} must be a finite non-negative distance")
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("Invalid screenshot-to-logical coordinate ratio")
        result[name] = value / ratio
    return result


_SWIPE_DIRECTIONS = ("up", "down", "left", "right")


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _js_round(value: float) -> int:
    """JavaScript Math.round: halves round towards +infinity."""
    return int(math.floor(value + 0.5))


def _swipe_center(locate: Any, name: str) -> dict[str, float]:
    center = locate.get("center") if isinstance(locate, dict) else None
    if not center or len(center) < 2:
        raise ValueError(f'Swipe "{name}" requires a located center point')
    return {"x": float(center[0]), "y": float(center[1])}


def normalize_swipe_param(
    param: dict[str, Any], screen_size: dict[str, Any]
) -> dict[str, Any]:
    """Resolve Swipe params into points, duration and repeat count.

    Mirrors upstream `normalizeSwipeParam`: `end` is mutually exclusive with
    `direction`/`distance`, the start defaults to the screen center, the end
    point is clamped to the screen bounds and repeat 0 means continuous mode
    capped at 10 repetitions.
    """
    width = float(screen_size["width"])
    height = float(screen_size["height"])

    duration = param.get("duration")
    if duration is None:
        duration = 300
    if not _is_finite_number(duration) or duration <= 0:
        raise ValueError("duration must be a positive finite number")

    repeat_count = param.get("repeat")
    if repeat_count is None:
        repeat_count = 1
    if (
        not _is_finite_number(repeat_count)
        or not float(repeat_count).is_integer()
        or repeat_count < 0
    ):
        raise ValueError("repeat must be a non-negative finite integer")

    start = param.get("start")
    if start:
        start_point = _swipe_center(start, "start")
    else:
        start_point = {"x": width / 2, "y": height / 2}

    end = param.get("end")
    direction = param.get("direction")
    distance = param.get("distance")
    if end:
        if direction is not None or distance is not None:
            raise ValueError(
                'Invalid Swipe parameters: "end" cannot be combined with '
                '"direction" or "distance". Use "end", optionally with "start", '
                "for an endpoint swipe."
            )
        end_point = _swipe_center(end, "end")
    else:
        if direction not in _SWIPE_DIRECTIONS or distance is None:
            raise ValueError(
                "Invalid Swipe parameters: a relative swipe requires both "
                '"direction" and a positive "distance".'
            )
        if not _is_finite_number(distance) or distance <= 0:
            raise ValueError(
                'Invalid Swipe parameters: "distance" must be a positive number.'
            )
        end_point = {
            "x": start_point["x"]
            + (
                distance
                if direction == "right"
                else -distance
                if direction == "left"
                else 0
            ),
            "y": start_point["y"]
            + (
                distance
                if direction == "down"
                else -distance
                if direction == "up"
                else 0
            ),
        }

    end_point["x"] = max(0.0, min(end_point["x"], width))
    end_point["y"] = max(0.0, min(end_point["y"], height))

    return {
        "start_point": start_point,
        "end_point": end_point,
        "duration": duration,
        "repeat_count": 10 if repeat_count == 0 else int(repeat_count),
    }


def normalize_pinch_param(
    param: dict[str, Any], screen_size: dict[str, Any]
) -> dict[str, Any]:
    """Resolve Pinch params into a center point and finger distances.

    Mirrors upstream `normalizePinchParam`: the center defaults to the middle
    of the screen, the fingers start a quarter of the shorter dimension apart
    and the optional distance is how much that gap changes.
    """
    width = float(screen_size["width"])
    height = float(screen_size["height"])

    direction = param.get("direction")
    if direction not in ("in", "out"):
        raise ValueError('Pinch direction must be "in" or "out"')

    duration = param.get("duration")
    if duration is None:
        duration = 500
    if not _is_finite_number(duration) or duration <= 0:
        raise ValueError("duration must be a positive finite number")

    locate = param.get("locate")
    if locate:
        center = _swipe_center(locate, "locate")
        center_x = _js_round(center["x"])
        center_y = _js_round(center["y"])
    else:
        center_x = _js_round(width / 2)
        center_y = _js_round(height / 2)

    base_distance = _js_round(min(width, height) / 4)
    finger_distance = param.get("distance")
    if finger_distance is None:
        finger_distance = base_distance
    if not _is_finite_number(finger_distance) or finger_distance <= 0:
        raise ValueError("distance must be a positive finite number")

    end_distance = (
        base_distance + finger_distance
        if direction == "out"
        else max(10, base_distance - finger_distance)
    )

    return {
        "center_x": center_x,
        "center_y": center_y,
        "start_distance": base_distance,
        "end_distance": end_distance,
        "duration": int(duration),
    }


# ---------------------------------------------------------------------------
# Input-primitive action factories (upstream device/index.ts).
# Platform adapters expose low-level primitives; these factories bind them to
# the planning action descriptors instead of duplicating gesture logic.
# ---------------------------------------------------------------------------

INPUT_LOCATE_DESCRIPTION = (
    "the position of the placeholder or text content in the target input "
    "field. If there is no content, locate the center of the input field."
)

ACTION_TAP_PARAM_SCHEMA = {
    "locate": {"type": "locate", "description": "The element to be tapped"}
}

REGISTER_FILE_CHOOSER_ACCEPT_PARAM_SCHEMA = {
    "files": {
        "type": "string | string[]",
        "description": (
            "File path(s) within the current aiAct call's "
            "fileChooserAllowedDir to use whenever a later action triggers a "
            "file chooser. fileChooserAllowedDir must be provided for this "
            "action. This setting replaces any previously registered file "
            "path(s)."
        ),
    }
}

ACTION_RIGHT_CLICK_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": "The element to be right clicked",
    }
}

ACTION_MIDDLE_CLICK_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": "The element to be middle clicked",
    }
}

ACTION_DOUBLE_CLICK_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": "The element to be double clicked",
    }
}

ACTION_HOVER_PARAM_SCHEMA = {
    "locate": {"type": "locate", "description": "The element to be hovered"}
}

ACTION_INPUT_PARAM_SCHEMA = {
    "value": {
        "type": "string | number",
        "description": (
            "The text to input. Provide the final content for replace mode, "
            "only the inserted characters for typeOnly mode, or an empty "
            "string when using clear mode to remove existing text."
        ),
    },
    "locate": {
        "type": "locate",
        "description": INPUT_LOCATE_DESCRIPTION,
        "optional": True,
    },
    "mode": {
        "type": '"replace" | "clear" | "typeOnly"',
        "description": (
            'Input mode: "replace" (default) - clear the field and input the '
            'value; "typeOnly" - type the value directly without clearing the '
            "field first, and should be set explicitly for incremental edits "
            'after moving the cursor; "clear" - clear the field without '
            "inputting new text."
        ),
        "optional": True,
    },
    "autoDismissKeyboard": {
        "type": "boolean",
        "description": (
            "If true, the keyboard will be dismissed after the input is "
            "completed. Do not set it unless the user asks you to do so."
        ),
        "optional": True,
    },
    "keyboardTypeDelay": {
        "type": "number",
        "description": (
            "Delay in milliseconds between keystrokes when typing. Passed "
            "through from device/user configuration. Do not set it unless the "
            "user asks you to do so."
        ),
        "optional": True,
    },
    "inputStrategy": {
        "type": '"legacy" | "sequential" | "bulk"',
        "description": (
            'Text input strategy: "legacy" (default) preserves the current '
            'platform behavior; "sequential" enters one Unicode code point at '
            'a time; "bulk" sends the complete text through one platform '
            "input operation when supported and requires keyboardTypeDelay to "
            "be omitted or set to 0. Do not set it unless the user asks you "
            "to do so."
        ),
        "optional": True,
    },
}

ACTION_KEYBOARD_PRESS_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": (
            "The optional element to click before pressing the key. Omit this "
            "when the key should operate on the currently focused element, "
            "especially when copying or cutting an existing text selection."
        ),
        "optional": True,
    },
    "keyName": {
        "type": "string",
        "description": (
            "The key to be pressed. Use '+' for key combinations, e.g., "
            "'Control+A', 'Shift+Enter'"
        ),
    },
}

ACTION_SCROLL_PARAM_SCHEMA = {
    "scrollType": {
        "type": (
            '"singleAction" | "scrollToBottom" | "scrollToTop" | '
            '"scrollToRight" | "scrollToLeft"'
        ),
        "description": (
            'The scroll behavior: "singleAction" for a single scroll action, '
            '"scrollToBottom" for scrolling all the way to the bottom by '
            "rapidly scrolling 5-10 times (skipping intermediate content "
            'until reaching the bottom), "scrollToTop" for scrolling all the '
            "way to the top by rapidly scrolling 5-10 times (skipping "
            'intermediate content until reaching the top), "scrollToRight" '
            "for scrolling all the way to the right by rapidly scrolling "
            'multiple times, "scrollToLeft" for scrolling all the way to the '
            "left by rapidly scrolling multiple times"
        ),
        "optional": True,
    },
    "direction": {
        "type": '"down" | "up" | "right" | "left"',
        "description": (
            "The direction toward the off-screen content to reveal. Quick "
            "mapping: want to see content below the current viewport -> "
            '"down"; above -> "up"; to the left -> "left"; to the right -> '
            '"right". This does not describe the movement direction of the '
            "content currently visible on the screen. Only effective when "
            'scrollType is "singleAction".'
        ),
        "optional": True,
    },
    "distance": {
        "type": "number",
        "description": (
            "Positive requested scroll amount in screen-coordinate units. On "
            "touch platforms, it controls the length of the swipe gesture "
            "used to scroll; on web and desktop platforms, it controls or "
            "approximates the wheel scroll delta. Only effective when "
            'scrollType is "singleAction".'
        ),
        "optional": True,
    },
    "locate": {
        "type": "locate",
        "description": (
            'Describe the target element to be scrolled on, like "the table" '
            'or "the list" or "the content area" or "the scrollable area". Do '
            'NOT provide a general intent like "scroll to find some element"'
        ),
        "optional": True,
    },
}

ACTION_DRAG_AND_DROP_PARAM_SCHEMA = {
    "from": {"type": "locate", "description": "The position to be dragged"},
    "to": {"type": "locate", "description": "The position to be dropped"},
}

ACTION_LONG_PRESS_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": "The element to be long pressed",
    },
    "duration": {
        "type": "number",
        "description": "Long press duration in milliseconds",
        "optional": True,
    },
}

ACTION_CLEAR_INPUT_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": "The input field to be cleared",
        "optional": True,
    }
}

ACTION_CURSOR_MOVE_PARAM_SCHEMA = {
    "direction": {
        "type": '"left" | "right"',
        "description": "The direction to move the cursor",
    },
    "times": {
        "type": "number",
        "description": (
            "The number of times to move the cursor in the specified direction"
        ),
        "optional": True,
    },
}

ACTION_PINCH_PARAM_SCHEMA = {
    "locate": {
        "type": "locate",
        "description": (
            "The element to pinch on. If not specified, the center of the "
            "screen will be used"
        ),
        "optional": True,
    },
    "direction": {
        "type": '"in" | "out"',
        "description": (
            'Pinch direction. "in" = pinch fingers together (zoom out / '
            'shrink), "out" = spread fingers apart (zoom in / enlarge).'
        ),
    },
    "distance": {
        "type": "number",
        "description": (
            "The amount by which the distance between the two fingers "
            "changes, in pixels. Defaults to a quarter of the shorter screen "
            "dimension."
        ),
        "optional": True,
    },
    "duration": {
        "type": "number",
        "description": "Duration of the pinch gesture in milliseconds",
        "optional": True,
    },
}

ACTION_SLEEP_PARAM_SCHEMA = {
    "timeMs": {
        "type": "number",
        "description": (
            "Sleep duration in milliseconds, defaults to 1000ms (1 second)"
        ),
        "optional": True,
    }
}


def _lookup_key(name: Any) -> str:
    return "".join(char for char in str(name).lower() if char.isalnum())


def _snake_name(name: Any) -> str:
    step = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(name))
    step = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step)
    return step.lower()


def _field(source: Any, name: str, default: Any = None) -> Any:
    """Read a camelCase/snake_case field from a dict or an object."""
    if source is None:
        return default
    if isinstance(source, dict):
        wanted = _lookup_key(name)
        for key, value in source.items():
            if _lookup_key(key) == wanted:
                return value
        return default
    missing = object()
    value = getattr(source, name, missing)
    if value is not missing:
        return value
    return getattr(source, _snake_name(name), default)


def _option(
    options: Any, snake_name: str, camel_name: str | None = None, default: Any = None
) -> Any:
    value = _field(options, snake_name, None)
    if value is not None:
        return value
    if camel_name is not None:
        return _field(options, camel_name, default)
    return default


async def _invoke(fn: Any, *args: Any) -> Any:
    """Call a primitive, awaiting it when it is async."""
    result = fn(*args)
    if inspect.isawaitable(result):
        result = await result
    return result


def _point_from_locate(locate: Any, missing_message: str) -> dict[str, Any]:
    center = (
        locate.get("center")
        if isinstance(locate, dict)
        else getattr(locate, "center", None)
    )
    if locate is None or not center or len(center) < 2:
        raise ValueError(missing_message)
    return {"x": center[0], "y": center[1]}


def _define_action(
    *,
    name: str,
    description: str,
    call: Callable[[dict[str, Any], Any], Any],
    param_schema: dict[str, Any] | None = None,
    locate_fields: list[str] | None = None,
    distance_fields: list[str] | None = None,
    sample: dict[str, Any] | None = None,
    interface_alias: str | None = None,
    supported_by_system_one: bool = False,
    delay_before_runner: float | None = None,
    delay_after_runner: float | None = None,
) -> DeviceAction:
    """Build a descriptor whose executor resolves locate params then calls `call`."""
    locate_field_names = list(locate_fields or [])

    async def execute(
        param: dict[str, Any] | None = None,
        device: Any = None,
        locate_fn: Any = None,
    ) -> Any:
        resolved = dict(param or {})
        for field_name in locate_field_names:
            locate = resolved.get(field_name)
            if (
                isinstance(locate, dict)
                and "center" not in locate
                and locate_fn is not None
                and locate.get("prompt")
            ):
                located = await locate_fn(locate)
                resolved[field_name] = {**locate, "center": list(located["center"])}
        return await call(resolved, None)

    return DeviceAction(
        name=name,
        description=description,
        param_schema=param_schema or {},
        locate_fields=locate_field_names,
        distance_fields=list(distance_fields or []),
        sample=sample,
        interface_alias=interface_alias,
        supported_by_system_one=supported_by_system_one,
        execute=execute,
        delay_before_runner=delay_before_runner,
        delay_after_runner=delay_after_runner,
    )


def _define_located_point_action(
    *,
    name: str,
    description: str,
    primitive: Callable[[dict[str, Any]], Any],
    param_schema: dict[str, Any],
    sample: dict[str, Any],
    missing_locate_message: str,
    interface_alias: str | None = None,
    supported_by_system_one: bool = False,
    call_with_param: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        point = _point_from_locate(param.get("locate"), missing_locate_message)
        if call_with_param is not None:
            await call_with_param(point, param)
            return
        await _invoke(primitive, point)

    return _define_action(
        name=name,
        description=description,
        call=call,
        param_schema=param_schema,
        locate_fields=["locate"],
        sample=sample,
        interface_alias=interface_alias,
        supported_by_system_one=supported_by_system_one,
    )


def define_action_tap(
    tap: Callable[[dict[str, Any]], Any],
) -> DeviceAction:
    return _define_located_point_action(
        name="Tap",
        supported_by_system_one=True,
        description="Tap the element",
        interface_alias="aiTap",
        primitive=tap,
        param_schema=ACTION_TAP_PARAM_SCHEMA,
        sample={"locate": {"prompt": 'the "Submit" button'}},
        missing_locate_message="Element not found, cannot tap",
    )


def define_action_register_file_chooser_accept(
    register: Callable[[Any], Any],
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        await _invoke(register, param.get("files"))

    return _define_action(
        name="RegisterFileChooserAccept",
        description=(
            "Configure files for file chooser dialogs triggered by later "
            "actions in this aiAct"
        ),
        call=call,
        param_schema=REGISTER_FILE_CHOOSER_ACCEPT_PARAM_SCHEMA,
        sample={"files": ["fixtures/document.pdf"]},
        interface_alias="registerFileChooserAccept",
    )


def define_action_right_click(
    right_click: Callable[[dict[str, Any]], Any],
) -> DeviceAction:
    return _define_located_point_action(
        name="RightClick",
        supported_by_system_one=True,
        description="Right click the element",
        interface_alias="aiRightClick",
        primitive=right_click,
        param_schema=ACTION_RIGHT_CLICK_PARAM_SCHEMA,
        sample={"locate": {"prompt": "the file icon on the desktop"}},
        missing_locate_message="Element not found, cannot right click",
    )


def define_action_middle_click(
    middle_click: Callable[[dict[str, Any]], Any],
) -> DeviceAction:
    return _define_located_point_action(
        name="MiddleClick",
        description="Middle click the element",
        interface_alias="aiMiddleClick",
        primitive=middle_click,
        param_schema=ACTION_MIDDLE_CLICK_PARAM_SCHEMA,
        sample={"locate": {"prompt": "the link to open in a new tab"}},
        missing_locate_message="Element not found, cannot middle click",
    )


def define_action_double_click(
    double_click: Callable[[dict[str, Any]], Any],
) -> DeviceAction:
    return _define_located_point_action(
        name="DoubleClick",
        supported_by_system_one=True,
        description="Double click the element",
        interface_alias="aiDoubleClick",
        primitive=double_click,
        param_schema=ACTION_DOUBLE_CLICK_PARAM_SCHEMA,
        sample={"locate": {"prompt": "the folder icon"}},
        missing_locate_message="Element not found, cannot double click",
    )


def define_action_hover(
    hover: Callable[[dict[str, Any]], Any],
) -> DeviceAction:
    return _define_located_point_action(
        name="Hover",
        supported_by_system_one=True,
        description="Move the mouse to the element",
        interface_alias="aiHover",
        primitive=hover,
        param_schema=ACTION_HOVER_PARAM_SCHEMA,
        sample={"locate": {"prompt": 'the navigation menu item "Products"'}},
        missing_locate_message="Element not found, cannot hover",
    )


def define_action_input(keyboard: Any) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        mode = param.get("mode") or "replace"
        # Backward compat: convert the deprecated 'append' to 'typeOnly'.
        if mode == "append":
            mode = "typeOnly"

        if mode == "clear":
            await _invoke(_field(keyboard, "clearInput"), param.get("locate"))
            return

        value = param.get("value")
        if not value:
            return

        options: dict[str, Any] = {
            "target": param.get("locate"),
            "replace": mode != "typeOnly",
            "auto_dismiss_keyboard": param.get("autoDismissKeyboard"),
        }
        options.update(input_options(param))
        if _field(context, "skipDefaultWait", False):
            options["skip_default_wait"] = True
        await _invoke(_field(keyboard, "typeText"), str(value), options)

    return _define_action(
        name="Input",
        description="Input the value into the element",
        call=call,
        param_schema=ACTION_INPUT_PARAM_SCHEMA,
        locate_fields=["locate"],
        sample={
            "value": "test@example.com",
            "locate": {"prompt": "the email input field"},
        },
        interface_alias="aiInput",
    )


def define_action_keyboard_press(
    keyboard_press: Callable[[str, dict[str, Any]], Any],
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        await _invoke(
            keyboard_press,
            param.get("keyName"),
            {"target": param.get("locate")},
        )

    return _define_action(
        name="KeyboardPress",
        description=(
            'Press a key or key combination, like "Enter", "Tab", "Escape", '
            'or "Control+A", "Shift+Enter". Do not use this to type text. '
            "Omit locate to operate on the current focus without clicking "
            "again, especially for Copy or Cut after text has been selected."
        ),
        call=call,
        param_schema=ACTION_KEYBOARD_PRESS_PARAM_SCHEMA,
        locate_fields=["locate"],
        sample={"keyName": "Enter"},
        interface_alias="aiKeyboardPress",
    )


def define_action_scroll(
    scroll: Callable[..., Any],
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        if _field(context, "skipDefaultWait", False):
            await _invoke(scroll, param, {"skip_default_wait": True})
        else:
            await _invoke(scroll, param)

    return _define_action(
        name="Scroll",
        description=(
            "Scroll a page or scrollable region to reveal off-screen content. "
            "Use Scroll when the goal is to browse content outside the "
            "current viewport. For direct gesture interactions, such as "
            "adjusting a slider or wheel picker, switching between paged "
            "cards or images, following an on-screen swipe gesture to "
            "continue or dismiss, or swiping an item to delete it, use Swipe "
            "instead if available in the current Action Space. Supports "
            "scrollToBottom/scrollToTop for boundary navigation. Default: "
            "direction `down`, scrollType `singleAction`, distance `null`."
        ),
        call=call,
        param_schema=ACTION_SCROLL_PARAM_SCHEMA,
        locate_fields=["locate"],
        distance_fields=["distance"],
        sample={
            "direction": "down",
            "scrollType": "singleAction",
            "locate": {"prompt": "the center of the product list area"},
        },
        interface_alias="aiScroll",
    )


def define_action_drag_and_drop(
    drag_and_drop: Callable[[dict[str, Any], dict[str, Any]], Any],
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        from_locate = param.get("from")
        to_locate = param.get("to")
        if not from_locate:
            raise ValueError('missing "from" param for drag and drop')
        if not to_locate:
            raise ValueError('missing "to" param for drag and drop')
        await _invoke(
            drag_and_drop,
            _point_from_locate(from_locate, 'missing "from" param for drag and drop'),
            _point_from_locate(to_locate, 'missing "to" param for drag and drop'),
        )

    return _define_action(
        name="DragAndDrop",
        description=(
            "Pick up a specific UI element and move it to a new position "
            "(e.g., reorder a card, move a file into a folder, sort list "
            "items). The element itself moves with your finger/mouse."
        ),
        call=call,
        param_schema=ACTION_DRAG_AND_DROP_PARAM_SCHEMA,
        locate_fields=["from", "to"],
        sample={
            "from": {"prompt": 'the "report.pdf" file icon'},
            "to": {"prompt": "the upload drop zone"},
        },
        interface_alias="aiDragAndDrop",
    )


def define_action_long_press(
    long_press: Callable[..., Any],
) -> DeviceAction:
    async def press(point: dict[str, Any], param: dict[str, Any]) -> None:
        await _invoke(long_press, point, {"duration": param.get("duration")})

    return _define_located_point_action(
        name="LongPress",
        description="Long press the element",
        interface_alias="aiLongPress",
        primitive=long_press,
        param_schema=ACTION_LONG_PRESS_PARAM_SCHEMA,
        sample={"locate": {"prompt": "the message bubble"}},
        missing_locate_message="LongPress requires an element to be located",
        call_with_param=press,
    )


def _create_swipe_param_schema(input_mode: str) -> dict[str, Any]:
    movement_source = "finger" if input_mode == "touch" else "pointer"

    return {
        "start": {
            "type": "locate",
            "description": (
                f"Optional starting point of the {movement_source} movement. "
                "Available in both relative and endpoint forms. If omitted, "
                "the center of the page is used."
            ),
            "optional": True,
        },
        "direction": {
            "type": '"up" | "down" | "left" | "right"',
            "description": (
                f"{'Finger' if movement_source == 'finger' else 'Pointer'} "
                f"movement direction. Quick mapping: move the "
                f'{movement_source} or content upward -> "up"; downward -> '
                '"down"; leftward -> "left"; rightward -> "right". Required '
                "together with a positive distance for a relative swipe. "
                "Omit when using end."
            ),
            "optional": True,
        },
        "distance": {
            "type": "number",
            "description": (
                f"Positive length of the {movement_source} movement in "
                "pixels. Required together with direction for a relative "
                "swipe. Omit when using end."
            ),
            "optional": True,
        },
        "end": {
            "type": "locate",
            "description": (
                f"Endpoint of the {movement_source} movement. Use for an "
                "endpoint swipe, optionally with start. Do not provide "
                "direction or distance when using end."
            ),
            "optional": True,
        },
        "duration": {
            "type": "number",
            "description": "Duration of the swipe gesture in milliseconds",
            "optional": True,
        },
        "repeat": {
            "type": "number",
            "description": (
                "The number of times to repeat the swipe gesture. 1 for "
                "default, 0 for continuous mode capped at 10 repeats"
            ),
            "optional": True,
        },
    }


ACTION_SWIPE_PARAM_SCHEMA = _create_swipe_param_schema("touch")


def normalize_mobile_swipe_param(
    param: dict[str, Any], screen_size: dict[str, Any]
) -> dict[str, Any]:
    """Deprecated alias for `normalize_swipe_param` (upstream name)."""
    return normalize_swipe_param(param, screen_size)


def define_action_swipe(config: Any) -> DeviceAction:
    swipe = _field(config, "swipe")
    size = _field(config, "size")
    input_mode = _field(config, "inputMode", "touch") or "touch"

    async def call(param: dict[str, Any], context: Any = None) -> None:
        normalized = normalize_swipe_param(param, await _invoke(size))
        start_point = normalized["start_point"]
        end_point = normalized["end_point"]
        for _ in range(normalized["repeat_count"]):
            await _invoke(
                swipe,
                start_point,
                end_point,
                {"duration": normalized["duration"]},
            )

    description = (
        "Perform a touch gesture that directly manipulates the UI (e.g., "
        "adjust a continuous control such as a slider or wheel picker, switch "
        "between paged cards or images, follow an on-screen swipe gesture to "
        "continue or dismiss, or swipe an item to delete it). For browsing "
        "off-screen content in a page or scrollable region, use Scroll "
        "instead. Choose exactly one movement form: (1) relative swipe — "
        'provide "direction" and a positive "distance"; or (2) endpoint swipe '
        '— provide "end". "start" is optional for both forms and defaults to '
        'the center of the page. Do not combine "end" with "direction" or '
        '"distance".'
        if input_mode == "touch"
        else (
            "Perform a primary-mouse-button gesture that continuously presses "
            "and moves the pointer across the desktop UI. Use it to adjust a "
            "continuous control such as a slider or wheel picker, switch "
            "between paged cards or images, follow an on-screen swipe gesture "
            "to continue or dismiss, or swipe an item to delete it. For "
            "browsing off-screen content in a page or scrollable region, use "
            "Scroll instead. Choose exactly one movement form: (1) relative "
            'swipe — provide "direction" and a positive "distance"; or (2) '
            'endpoint swipe — provide "end". "start" is optional for both '
            "forms and defaults to the center of the page. Do not combine "
            '"end" with "direction" or "distance".'
        )
    )

    return _define_action(
        name="Swipe",
        description=description,
        call=call,
        param_schema=(
            ACTION_SWIPE_PARAM_SCHEMA
            if input_mode == "touch"
            else _create_swipe_param_schema(input_mode)
        ),
        locate_fields=["start", "end"],
        distance_fields=["distance"],
        sample={
            "start": {"prompt": "center of the notification"},
            "end": {"prompt": "upper edge of the screen"},
        },
        interface_alias="aiSwipe",
    )


def define_action_clear_input(
    clear_input: Callable[..., Any],
) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        await _invoke(clear_input, param.get("locate"))

    return _define_action(
        name="ClearInput",
        supported_by_system_one=True,
        description=INPUT_LOCATE_DESCRIPTION,
        call=call,
        param_schema=ACTION_CLEAR_INPUT_PARAM_SCHEMA,
        locate_fields=["locate"],
        sample={"locate": {"prompt": "the search input field"}},
        interface_alias="aiClearInput",
    )


def define_action_cursor_move(config: Any) -> DeviceAction:
    keyboard = _field(config, "keyboard")
    sleep = _field(config, "sleep")

    async def call(param: dict[str, Any], context: Any = None) -> None:
        direction = param.get("direction")
        times = param.get("times")
        if times is None:
            times = 1

        cursor_move = _field(keyboard, "cursorMove")
        if cursor_move is not None:
            await _invoke(cursor_move, direction, times)
            return

        wait = sleep
        if wait is None:

            async def wait(time_ms: float) -> None:
                await asyncio.sleep(time_ms / 1000)

        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(int(times)):
            await _invoke(_field(keyboard, "keyboardPress"), arrow_key)
            await _invoke(wait, 100)

    return _define_action(
        name="CursorMove",
        description=(
            "Move the text cursor (caret) left or right within an input field "
            "or text area. Use this to reposition the cursor without "
            "selecting text."
        ),
        call=call,
        param_schema=ACTION_CURSOR_MOVE_PARAM_SCHEMA,
        sample={"direction": "left", "times": 3},
    )


def define_action_pinch(config: Any) -> DeviceAction | None:
    pinch = _field(config, "pinch")
    if pinch is None:
        return None
    size = _field(config, "size")

    async def call(param: dict[str, Any], context: Any = None) -> None:
        normalized = normalize_pinch_param(param, await _invoke(size))
        await _invoke(
            pinch,
            {"x": normalized["center_x"], "y": normalized["center_y"]},
            {
                "start_distance": normalized["start_distance"],
                "end_distance": normalized["end_distance"],
                "duration": normalized["duration"],
            },
        )

    return _define_action(
        name="Pinch",
        description=(
            'Perform a two-finger pinch gesture. Use direction "in" to '
            'pinch fingers together (zoom out), or "out" to spread fingers '
            "apart (zoom in). Optionally specify distance for the amount by "
            "which the distance between the two fingers changes."
        ),
        call=call,
        param_schema=ACTION_PINCH_PARAM_SCHEMA,
        locate_fields=["locate"],
        distance_fields=["distance"],
        sample={
            "locate": {"prompt": "the map area"},
            "direction": "out",
            "distance": 200,
        },
        interface_alias="aiPinch",
    )


def define_action_sleep(abort_signal: Any = None) -> DeviceAction:
    async def call(param: dict[str, Any], context: Any = None) -> None:
        signal = abort_signal or _field(context, "signal")
        duration = param.get("timeMs")
        if duration is None:
            duration = 1000
        if signal is not None:
            signal.throw_if_aborted()
        await asyncio.sleep(max(float(duration), 0) / 1000)
        if signal is not None:
            signal.throw_if_aborted()

    return _define_action(
        name="Sleep",
        description=(
            "Wait for a specified duration before continuing. Defaults to 1 "
            "second (1000ms) if not specified."
        ),
        call=call,
        param_schema=ACTION_SLEEP_PARAM_SCHEMA,
        sample={"timeMs": 2000},
    )


def resolve_swipe_input_primitive(
    input: Any,
) -> dict[str, Any] | None:
    """Resolve the canonical swipe primitive; touch is preferred over mouse."""
    pointer = _field(input, "pointer")
    touch = _field(input, "touch")

    touch_swipe = _field(touch, "swipe")
    if touch_swipe is not None:
        return {"swipe": touch_swipe, "input_mode": "touch"}

    pointer_swipe = _field(pointer, "swipe")
    if pointer_swipe is not None:
        return {"swipe": pointer_swipe, "input_mode": "mouse"}

    return None


def _define_system_input_action(config: Any, primitive: Any) -> DeviceAction:
    async def execute(
        param: dict[str, Any] | None = None,
        device: Any = None,
        locate_fn: Any = None,
    ) -> None:
        await _invoke(primitive)

    return DeviceAction(
        name=_field(config, "name"),
        description=_field(config, "description") or "",
        param_schema=None,
        sample=None,
        interface_alias=_field(config, "interfaceAlias"),
        supported_by_system_one=bool(_field(config, "supportedBySystemOne", False)),
        execute=execute,
        delay_before_runner=_field(config, "delayBeforeRunner"),
        delay_after_runner=_field(config, "delayAfterRunner"),
    )


def define_actions_from_input_primitives(
    input: Any,
    options: Any = None,
) -> list[DeviceAction]:
    """Build the planning action set from low-level input primitives."""
    actions: list[DeviceAction | None] = []
    pointer = _field(input, "pointer")
    keyboard = _field(input, "keyboard")
    scroll = _field(input, "scroll")
    touch = _field(input, "touch")
    system = _field(input, "system")

    if pointer is not None:
        actions.append(define_action_tap(_field(pointer, "tap")))
        double_click = _field(pointer, "doubleClick")
        if double_click is not None:
            actions.append(define_action_double_click(double_click))
        right_click = _field(pointer, "rightClick")
        if right_click is not None:
            actions.append(define_action_right_click(right_click))
        middle_click = _field(pointer, "middleClick")
        if middle_click is not None:
            actions.append(define_action_middle_click(middle_click))
        hover = _field(pointer, "hover")
        if hover is not None:
            actions.append(define_action_hover(hover))
        drag_and_drop = _field(pointer, "dragAndDrop")
        if drag_and_drop is not None:
            actions.append(define_action_drag_and_drop(drag_and_drop))
        long_press = _field(pointer, "longPress")
        if long_press is not None:
            actions.append(define_action_long_press(long_press))

    if keyboard is not None:
        actions.append(define_action_input(keyboard))
        actions.append(define_action_clear_input(_field(keyboard, "clearInput")))
        actions.append(define_action_keyboard_press(_field(keyboard, "keyboardPress")))
        actions.append(
            define_action_cursor_move(
                {"keyboard": keyboard, "sleep": _option(options, "sleep")}
            )
        )

    if scroll is not None:
        actions.append(define_action_scroll(_field(scroll, "scroll")))

    size = _option(options, "size")
    swipe_config = resolve_swipe_input_primitive({"pointer": pointer, "touch": touch})
    if (
        swipe_config is not None
        and size is not None
        and _option(options, "include_swipe", "includeSwipe", True) is not False
    ):
        actions.append(define_action_swipe({**swipe_config, "size": size}))

    pinch = _field(touch, "pinch")
    if (
        pinch is not None
        and size is not None
        and _option(options, "include_pinch", "includePinch", True) is not False
    ):
        actions.append(define_action_pinch({"pinch": pinch, "size": size}))

    system_actions = _option(options, "system_actions", "systemActions")
    if system is not None and system_actions is not None:
        for name in ("backButton", "homeButton", "recentAppsButton"):
            primitive = _field(system, name)
            config = _field(system_actions, name)
            if primitive is not None and config is not None:
                actions.append(_define_system_input_action(config, primitive))

    return [action for action in actions if action is not None]


def create_default_mobile_actions(context: Any) -> list[DeviceAction]:
    """The default mobile action set built from `context.input` primitives."""
    return define_actions_from_input_primitives(
        _field(context, "input"),
        {
            "size": _field(context, "size"),
            "sleep": _field(context, "sleep"),
            "system_actions": _field(context, "systemActions"),
        },
    )


# ---------------------------------------------------------------------------
# Action executors. `device` is the platform interface; `locate_fn` resolves a
# locate param ({prompt, locatedPixelResult?}) to {'center': (x, y), 'rect'?}.
# ---------------------------------------------------------------------------


async def _resolve_locate_point(
    locate_param: dict[str, Any], locate_fn
) -> dict[str, Any]:
    if not isinstance(locate_param, dict) or not locate_param.get("prompt"):
        raise ValueError("locate parameter requires a prompt")
    return await locate_fn(locate_param)


def _make_tap(executor: str) -> Callable[..., Any]:
    async def execute(param: dict[str, Any], device: Any, locate_fn) -> None:
        locate = param.get("locate")
        if locate is None:
            raise ValueError(f"{executor} requires a locate parameter")
        point = await _resolve_locate_point(locate, locate_fn)
        x, y = point["center"]
        method = getattr(device, executor)
        if executor == "tap":
            await method(x, y)
        else:
            await method(x, y)

    return execute


async def _execute_input(param: dict[str, Any], device: Any, locate_fn) -> None:
    mode = param.get("mode") or "replace"
    # Backward compat: upstream converts the deprecated 'append' to 'typeOnly'.
    if mode == "append":
        mode = "typeOnly"

    if mode == "clear":
        locate = param.get("locate")
        if locate is not None:
            point = await _resolve_locate_point(locate, locate_fn)
            x, y = point["center"]
            await device.tap(x, y)
            await asyncio.sleep(0.1)
        await device.clear_input()
        return

    value = param.get("value")
    if value is None or value == "":
        return
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        x, y = point["center"]
        if hasattr(device, "input_text_at"):
            # Harmony uitest inputText uses (x, y) to identify the field
            await device.input_text_at(x, y, str(value) if mode != "clear" else "")
            return
        await device.tap(x, y)
        await asyncio.sleep(0.2)
    if mode == "replace" and _supports(device, "replace_input"):
        await device.replace_input(
            str(value), **_supported_kwargs(device.replace_input, input_options(param))
        )
        return
    await device.input_text(
        str(value), **_supported_kwargs(device.input_text, input_options(param))
    )


async def _execute_keyboard_press(
    param: dict[str, Any], device: Any, locate_fn
) -> None:
    key_name = param.get("keyName")
    if not key_name:
        raise ValueError("KeyboardPress requires keyName")
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        x, y = point["center"]
        await device.tap(x, y)
        await asyncio.sleep(0.1)
    await device.keyboard_press(str(key_name))


async def _execute_scroll(param: dict[str, Any], device: Any, locate_fn) -> None:
    direction = param.get("direction") or "down"
    distance = param.get("distance")
    scroll_type = param.get("scrollType") or "singleAction"
    kwargs: dict[str, Any] = {"scroll_type": scroll_type}
    if distance is not None:
        kwargs["distance"] = distance
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        kwargs["point"] = point["center"]
    await device.scroll(direction, **_scroll_supported_kwargs(device, kwargs))


async def _execute_clear_input(param: dict[str, Any], device: Any, locate_fn) -> None:
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        x, y = point["center"]
        await device.tap(x, y)
        await asyncio.sleep(0.1)
    if _supports(device, "clear_input"):
        await device.clear_input()
    else:
        await device.keyboard_press("Control+A")
        await device.keyboard_press("Delete")


async def _execute_sleep(param: dict[str, Any], device: Any, locate_fn) -> None:
    time_ms = param.get("timeMs") or 1000
    try:
        time_ms = max(0, min(int(time_ms), 5 * 60 * 1000))
    except (TypeError, ValueError):
        time_ms = 1000
    await asyncio.sleep(time_ms / 1000)


async def _execute_cursor_move(param: dict[str, Any], device: Any, locate_fn) -> None:
    direction = param.get("direction")
    if direction not in ("left", "right"):
        raise ValueError('CursorMove direction must be "left" or "right"')
    times = param.get("times") or 1
    try:
        times = max(1, int(times))
    except (TypeError, ValueError):
        times = 1
    if _supports(device, "cursor_move"):
        await device.cursor_move(direction, times)
        return
    arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
    for _ in range(times):
        await device.keyboard_press(arrow_key)
        await asyncio.sleep(0.1)


async def _execute_navigate(param: dict[str, Any], device: Any, locate_fn) -> None:
    url = param.get("url")
    if not url or not str(url).strip():
        raise ValueError("Navigate requires a non-empty url parameter")
    if not _supports(device, "navigate_to"):
        raise NotImplementedError("Navigate is not supported on this interface")
    await device.navigate_to(str(url))


async def _execute_reload(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "reload"):
        raise NotImplementedError("Reload is not supported on this interface")
    await device.reload()


async def _execute_go_back(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "go_back"):
        raise NotImplementedError("GoBack is not supported on this interface")
    await device.go_back()


async def _execute_go_forward(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "go_forward"):
        raise NotImplementedError("GoForward is not supported on this interface")
    await device.go_forward()


async def _resolve_screen_size(device: Any) -> dict[str, float]:
    """Logical screen size used to normalize swipe points."""
    size_fn = getattr(device, "size", None)
    if size_fn is not None:
        size = await size_fn()
        if isinstance(size, dict):
            return {"width": float(size["width"]), "height": float(size["height"])}
        return {"width": float(size.width), "height": float(size.height)}
    context = await device.get_context()
    return {
        "width": float(context.size.width),
        "height": float(context.size.height),
    }


async def _execute_swipe(param: dict[str, Any], device: Any, locate_fn) -> None:
    resolved = dict(param)
    if resolved.get("start"):
        point = await _resolve_locate_point(resolved["start"], locate_fn)
        resolved["start"] = {"center": list(point["center"])}
    if resolved.get("end"):
        point = await _resolve_locate_point(resolved["end"], locate_fn)
        resolved["end"] = {"center": list(point["center"])}

    normalized = normalize_swipe_param(resolved, await _resolve_screen_size(device))
    direction = resolved.get("direction")
    distance = resolved.get("distance")
    duration = int(normalized["duration"])
    repeat_count = normalized["repeat_count"]

    def _swipe_kwargs() -> dict[str, Any]:
        kwargs: dict[str, Any] = {"distance": distance}
        if _accepts_keyword(device.swipe, "duration"):
            kwargs["duration"] = duration
        return kwargs

    # A plain relative swipe keeps using the platform direction primitive so
    # the device-specific centering/clamping behaviour is unchanged.
    if (
        not resolved.get("start")
        and not resolved.get("end")
        and _supports(device, "swipe")
    ):
        for _ in range(repeat_count):
            await device.swipe(direction, **_swipe_kwargs())
        return

    if _supports(device, "swipe_points"):
        point_kwargs: dict[str, Any] = {}
        if _accepts_keyword(device.swipe_points, "duration"):
            point_kwargs["duration"] = duration
        start_point = [
            normalized["start_point"]["x"],
            normalized["start_point"]["y"],
        ]
        end_point = [normalized["end_point"]["x"], normalized["end_point"]["y"]]
        for _ in range(repeat_count):
            await device.swipe_points(start_point, end_point, **point_kwargs)
        return

    if _supports(device, "swipe") and direction is not None:
        for _ in range(repeat_count):
            await device.swipe(direction, **_swipe_kwargs())
        return

    if direction is not None:
        await device.scroll(direction, distance=distance)
        return

    raise NotImplementedError("Swipe endpoint form is not supported on this interface")


async def _execute_pull_gesture(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "pull_gesture"):
        raise NotImplementedError("PullGesture is not supported on this interface")
    direction = param.get("direction")
    if direction not in ("up", "down"):
        raise ValueError('PullGesture requires a direction of "up" or "down"')
    start_point = None
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        start_point = list(point["center"])
    await device.pull_gesture(
        direction,
        start_point=start_point,
        distance=param.get("distance"),
        duration=param.get("duration"),
    )


async def _execute_drag_and_drop(param: dict[str, Any], device: Any, locate_fn) -> None:
    from_locate = param.get("from")
    to_locate = param.get("to")
    if not from_locate:
        raise ValueError('DragAndDrop requires a "from" locate parameter')
    if not to_locate:
        raise ValueError('DragAndDrop requires a "to" locate parameter')
    if not _supports(device, "drag_and_drop"):
        raise NotImplementedError("DragAndDrop is not supported on this interface")
    from_point = await _resolve_locate_point(from_locate, locate_fn)
    to_point = await _resolve_locate_point(to_locate, locate_fn)
    await device.drag_and_drop(from_point["center"], to_point["center"])


async def _execute_long_press(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "long_press"):
        raise NotImplementedError("LongPress is not supported on this interface")
    locate = param.get("locate")
    if locate is None:
        raise ValueError("LongPress requires a locate parameter")
    point = await _resolve_locate_point(locate, locate_fn)
    x, y = point["center"]
    duration = param.get("duration")
    if duration is not None:
        await device.long_press(x, y, duration=int(duration))
    else:
        await device.long_press(x, y)


def build_web_action_space() -> list[DeviceAction]:
    """The web/desktop action space (upstream web-integration default set)."""
    return [
        DeviceAction(
            name="Tap",
            supported_by_system_one=True,
            description="Tap the element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to be tapped",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": 'the "Submit" button'}},
            interface_alias="aiTap",
            primitive="tap",
            execute=_make_tap("tap"),
        ),
        DeviceAction(
            name="RightClick",
            supported_by_system_one=True,
            description="Right click the element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to be right clicked",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": "the file icon"}},
            interface_alias="aiRightClick",
            primitive="right_click",
            execute=_make_tap("right_click"),
        ),
        DeviceAction(
            name="MiddleClick",
            supported_by_system_one=True,
            description="Middle click the element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to be middle clicked",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": "the link to open in a new tab"}},
            interface_alias="aiMiddleClick",
            primitive="middle_click",
            execute=_make_tap("middle_click"),
        ),
        DeviceAction(
            name="DoubleClick",
            supported_by_system_one=True,
            description="Double click the element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to be double clicked",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": "the word to select"}},
            interface_alias="aiDoubleClick",
            primitive="double_click",
            execute=_make_tap("double_click"),
        ),
        DeviceAction(
            name="Hover",
            supported_by_system_one=True,
            description="Move the mouse cursor over the element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to hover over",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": "the user avatar in the top right"}},
            interface_alias="aiHover",
            primitive="hover",
            execute=_make_tap("hover"),
        ),
        DeviceAction(
            name="Pinch",
            description=(
                "Perform a two-finger pinch gesture. Use direction 'in' to pinch "
                "fingers together (zoom out / shrink), or 'out' to spread fingers "
                "apart (zoom in / enlarge). Optionally specify distance for how "
                "far each finger moves."
            ),
            param_schema={
                "direction": {
                    "type": '"in" | "out"',
                    "description": (
                        'Pinch direction. "in" = pinch fingers together '
                        '(zoom out / shrink), "out" = spread fingers apart '
                        "(zoom in / enlarge)."
                    ),
                },
                "locate": {
                    "type": "locate",
                    "description": (
                        "The element to pinch on. If not specified, the center "
                        "of the screen will be used"
                    ),
                    "optional": True,
                },
                "distance": {
                    "type": "number",
                    "description": (
                        "The amount by which the distance between the two "
                        "fingers changes, in pixels. Defaults to a quarter of "
                        "the shorter screen dimension."
                    ),
                    "optional": True,
                },
                "duration": {
                    "type": "number",
                    "description": "Duration of the pinch gesture in milliseconds",
                    "optional": True,
                },
            },
            locate_fields=["locate"],
            distance_fields=["distance"],
            sample={
                "direction": "out",
                "distance": 200,
                "locate": {"prompt": "the map area"},
            },
            interface_alias="aiPinch",
            primitive="pinch",
            execute=_execute_pinch,
        ),
        DeviceAction(
            name="DragAndDrop",
            description=(
                "Pick up a specific UI element and move it to a new position "
                "(e.g., reorder a card, move a file into a folder, sort list "
                "items). The element itself moves with your finger/mouse."
            ),
            param_schema={
                "from": {
                    "type": "locate",
                    "description": "The position to be dragged",
                },
                "to": {
                    "type": "locate",
                    "description": "The position to be dropped",
                },
            },
            locate_fields=["from", "to"],
            sample={
                "from": {"prompt": 'the "report.pdf" file icon'},
                "to": {"prompt": "the upload drop zone"},
            },
            interface_alias="aiDragAndDrop",
            primitive="drag_and_drop",
            execute=_execute_drag_and_drop,
        ),
        DeviceAction(
            name="Input",
            description="Input the value into the element",
            param_schema={
                "value": {
                    "type": "string",
                    "description": "The value to input",
                },
                "locate": {
                    "type": "locate",
                    "description": "The element to input into",
                    "optional": True,
                },
                "mode": {
                    "type": '"replace" | "clear" | "typeOnly"',
                    "description": (
                        'Input mode: "replace" (default) - clear the field and '
                        'input the value; "typeOnly" - type the value directly '
                        "without clearing the field first, and should be set "
                        "explicitly for incremental edits after moving the "
                        'cursor; "clear" - clear the field without inputting new text.'
                    ),
                    "optional": True,
                },
                "autoDismissKeyboard": {
                    "type": "boolean",
                    "description": (
                        "If true, the keyboard will be dismissed after the input "
                        "is completed. Do not set it unless the user asks you to "
                        "do so."
                    ),
                    "optional": True,
                },
                "keyboardTypeDelay": {
                    "type": "number",
                    "description": (
                        "Delay in milliseconds between keystrokes when typing. "
                        "Passed through from device/user configuration. Do not "
                        "set it unless the user asks you to do so."
                    ),
                    "optional": True,
                },
                "inputStrategy": {
                    "type": '"legacy" | "sequential" | "bulk"',
                    "description": (
                        'Text input strategy: "legacy" (default) preserves the '
                        'current platform behavior; "sequential" enters one '
                        'Unicode code point at a time; "bulk" sends the complete '
                        "text through one platform input operation when "
                        "supported and requires keyboardTypeDelay to be omitted "
                        "or set to 0. Do not set it unless the user asks you to "
                        "do so."
                    ),
                    "optional": True,
                },
            },
            locate_fields=["locate"],
            sample={
                "value": "test@example.com",
                "locate": {"prompt": "the email input field"},
            },
            interface_alias="aiInput",
            primitive="input_text",
            execute=_execute_input,
        ),
        DeviceAction(
            name="KeyboardPress",
            description=(
                'Press a key or key combination, like "Enter", "Tab", "Escape", or '
                '"Control+A", "Shift+Enter". Do not use this to type text. Omit '
                "locate to operate on the current focus without clicking again, "
                "especially for Copy or Cut after text has been selected."
            ),
            param_schema={
                "keyName": {
                    "type": "string",
                    "description": (
                        "The key to be pressed. Use '+' for key combinations, "
                        "e.g., 'Control+A', 'Shift+Enter'"
                    ),
                },
                "locate": {
                    "type": "locate",
                    "description": (
                        "The optional element to click before pressing the key. "
                        "Omit this when the key should operate on the currently "
                        "focused element, especially when copying or cutting an "
                        "existing text selection."
                    ),
                    "optional": True,
                },
            },
            locate_fields=["locate"],
            sample={"keyName": "Enter"},
            interface_alias="aiKeyboardPress",
            primitive="keyboard_press",
            execute=_execute_keyboard_press,
        ),
        DeviceAction(
            name="Scroll",
            description=(
                "Scroll a page or scrollable region to reveal off-screen content. "
                "Use Scroll when the goal is to browse content outside the current "
                "viewport. For direct gesture interactions, such as adjusting a "
                "slider or wheel picker, switching between paged cards or images, "
                "following an on-screen swipe gesture to continue or dismiss, or "
                "swiping an item to delete it, use Swipe instead if available in "
                "the current Action Space. Supports scrollToBottom/scrollToTop for "
                "boundary navigation. Default: direction `down`, scrollType "
                "`singleAction`, distance `null`."
            ),
            param_schema={
                "scrollType": {
                    "type": '"singleAction" | "scrollToBottom" | "scrollToTop" | "scrollToRight" | "scrollToLeft"',
                    "description": (
                        'The scroll behavior: "singleAction" for a single scroll '
                        'action, "scrollToBottom" for scrolling all the way to the '
                        "bottom by rapidly scrolling 5-10 times (skipping "
                        "intermediate content until reaching the bottom), "
                        '"scrollToTop" for scrolling all the way to the top by '
                        "rapidly scrolling 5-10 times (skipping intermediate "
                        'content until reaching the top), "scrollToRight" for '
                        "scrolling all the way to the right by rapidly scrolling "
                        'multiple times, "scrollToLeft" for scrolling all the way '
                        "to the left by rapidly scrolling multiple times"
                    ),
                    "optional": True,
                },
                "direction": {
                    "type": '"down" | "up" | "right" | "left"',
                    "description": (
                        "The direction toward the off-screen content to reveal. "
                        "Quick mapping: want to see content below the current "
                        'viewport -> "down"; above -> "up"; to the left -> '
                        '"left"; to the right -> "right". This does not describe '
                        "the movement direction of the content currently visible "
                        "on the screen. Only effective when scrollType is "
                        '"singleAction".'
                    ),
                    "optional": True,
                },
                "distance": {
                    "type": "number",
                    "description": (
                        "Positive requested scroll amount in screen-coordinate "
                        "units. On touch platforms, it controls the length of the "
                        "swipe gesture used to scroll; on web and desktop "
                        "platforms, it controls or approximates the wheel scroll "
                        'delta. Only effective when scrollType is "singleAction".'
                    ),
                    "optional": True,
                },
                "locate": {
                    "type": "locate",
                    "description": (
                        'Describe the target element to be scrolled on, like "the '
                        'table" or "the list" or "the content area" or "the '
                        'scrollable area". Do NOT provide a general intent like '
                        '"scroll to find some element"'
                    ),
                    "optional": True,
                },
            },
            locate_fields=["locate"],
            distance_fields=["distance"],
            sample={
                "direction": "down",
                "scrollType": "singleAction",
                "locate": {"prompt": "the center of the product list area"},
            },
            interface_alias="aiScroll",
            primitive="scroll",
            execute=_execute_scroll,
        ),
        DeviceAction(
            name="ClearInput",
            supported_by_system_one=True,
            description="Clear the text content of an input element",
            param_schema={
                "locate": {
                    "type": "locate",
                    "description": "The element to clear",
                }
            },
            locate_fields=["locate"],
            sample={"locate": {"prompt": "the search input field"}},
            interface_alias="aiClearInput",
            primitive="clear_input",
            execute=_execute_clear_input,
        ),
        DeviceAction(
            name="Sleep",
            description="Wait for a specified amount of time",
            param_schema={
                "timeMs": {
                    "type": "number",
                    "description": "Milliseconds to wait. Default: 1000",
                    "optional": True,
                }
            },
            locate_fields=[],
            sample={"timeMs": 3000},
            interface_alias="aiSleep",
            execute=_execute_sleep,
        ),
        DeviceAction(
            name="CursorMove",
            description=(
                "Move the text cursor (caret) left or right within an input field "
                "or text area. Use this to reposition the cursor without selecting "
                "text."
            ),
            param_schema={
                "direction": {
                    "type": '"left" | "right"',
                    "description": "The direction to move the cursor",
                },
                "times": {
                    "type": "number",
                    "description": (
                        "The number of times to move the cursor in the specified "
                        "direction. Default: 1"
                    ),
                    "optional": True,
                },
            },
            locate_fields=[],
            sample={"direction": "left", "times": 3},
            interface_alias="aiCursorMove",
            primitive="cursor_move",
            execute=_execute_cursor_move,
        ),
        DeviceAction(
            name="Navigate",
            description=(
                "Navigate the browser to a specified URL. Opens the URL in the "
                "current tab."
            ),
            param_schema={
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                }
            },
            locate_fields=[],
            sample={"url": "https://www.example.com"},
            interface_alias="aiNavigate",
            primitive="navigate_to",
            execute=_execute_navigate,
        ),
        DeviceAction(
            name="Reload",
            supported_by_system_one=True,
            description="Reload the current page",
            locate_fields=[],
            interface_alias="aiReload",
            primitive="reload",
            execute=_execute_reload,
        ),
        DeviceAction(
            name="GoBack",
            supported_by_system_one=True,
            description="Navigate back in browser history",
            locate_fields=[],
            interface_alias="aiGoBack",
            primitive="go_back",
            execute=_execute_go_back,
        ),
        DeviceAction(
            name="GoForward",
            supported_by_system_one=True,
            description="Navigate forward in browser history",
            locate_fields=[],
            interface_alias="aiGoForward",
            primitive="go_forward",
            execute=_execute_go_forward,
        ),
    ]


async def _execute_run_adb_shell(param: dict[str, Any], device: Any, locate_fn) -> Any:
    command = param.get("command")
    if not command:
        raise ValueError("RunAdbShell requires a command parameter")
    if not hasattr(device, "run_adb_shell"):
        raise NotImplementedError("RunAdbShell is not supported on this interface")
    timeout = param.get("timeout")
    if timeout is not None:
        return await device.run_adb_shell(str(command), timeout=float(timeout))
    return await device.run_adb_shell(str(command))


async def _execute_launch(param: dict[str, Any], device: Any, locate_fn) -> None:
    uri = param.get("uri")
    if not uri or not str(uri).strip():
        raise ValueError("Launch requires a non-empty uri parameter")
    await device.launch_app(str(uri))


async def _execute_terminate(param: dict[str, Any], device: Any, locate_fn) -> None:
    uri = param.get("uri")
    if not uri or not str(uri).strip():
        raise ValueError("Terminate requires a non-empty uri parameter")
    await device.stop_app(str(uri))


async def _execute_pinch(param: dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "pinch"):
        raise NotImplementedError("Pinch is not supported on this interface")
    resolved = dict(param)
    if resolved.get("locate"):
        point_result = await _resolve_locate_point(resolved["locate"], locate_fn)
        resolved["locate"] = {"center": list(point_result["center"])}
    normalized = normalize_pinch_param(resolved, await _resolve_screen_size(device))
    await device.pinch(
        [normalized["center_x"], normalized["center_y"]],
        normalized["start_distance"],
        normalized["end_distance"],
        duration=normalized["duration"],
    )


async def _execute_run_hdc_shell(param: dict[str, Any], device: Any, locate_fn) -> Any:
    command = param.get("command")
    if not command or not str(command).strip():
        raise RuntimeError("RunHdcShell requires a non-empty command")
    if not hasattr(device, "run_hdc_shell"):
        raise NotImplementedError("RunHdcShell is not supported on this interface")
    return await device.run_hdc_shell(str(command))


_WDA_HTTP_METHODS = ("GET", "POST", "DELETE", "PUT")


async def _execute_run_wda_request(
    param: dict[str, Any], device: Any, locate_fn
) -> Any:
    method = str(param.get("method") or "").upper()
    if method not in _WDA_HTTP_METHODS:
        raise ValueError(
            f"RunWdaRequest requires one of {', '.join(_WDA_HTTP_METHODS)}"
        )
    endpoint = param.get("endpoint")
    if not endpoint or not str(endpoint).strip():
        raise ValueError("RunWdaRequest requires a non-empty endpoint")
    if not hasattr(device, "run_wda_request"):
        raise NotImplementedError("RunWdaRequest is not supported on this interface")
    return await device.run_wda_request(method, str(endpoint), param.get("data"))


def _make_harmony_system_action(method_name: str) -> Callable[..., Any]:
    async def execute(param: dict[str, Any], device: Any, locate_fn) -> None:
        await getattr(device, method_name)()

    return execute


def _make_system_action(method_name: str) -> Callable[..., Any]:
    async def execute(param: dict[str, Any], device: Any, locate_fn) -> None:
        await getattr(device, method_name)()

    return execute


_ANDROID_SHARED_ACTIONS = (
    "Tap",
    "Input",
    "KeyboardPress",
    "CursorMove",
    "Scroll",
    "ClearInput",
    "DragAndDrop",
    "Pinch",
    "Sleep",
)


def _swipe_action(input_mode: str = "touch") -> DeviceAction:
    """Swipe is exposed by touch and pointer devices (upstream defineActionSwipe)."""
    movement = "finger" if input_mode == "touch" else "pointer"
    if input_mode == "touch":
        description = (
            "Perform a touch gesture that directly manipulates the UI (e.g., "
            "adjust a continuous control such as a slider or wheel picker, "
            "switch between paged cards or images, follow an on-screen swipe "
            "gesture to continue or dismiss, or swipe an item to delete it). "
            "For browsing off-screen content in a page or scrollable region, "
            "use Scroll instead. Choose exactly one movement form: "
            '(1) relative swipe — provide "direction" and a positive '
            '"distance"; or (2) endpoint swipe — provide "end". "start" is '
            "optional for both forms and defaults to the center of the page. "
            'Do not combine "end" with "direction" or "distance".'
        )
    else:
        description = (
            "Perform a primary-mouse-button gesture that continuously presses "
            "and moves the pointer across the desktop UI. Use it to adjust a "
            "continuous control such as a slider or wheel picker, switch "
            "between paged cards or images, follow an on-screen swipe gesture "
            "to continue or dismiss, or swipe an item to delete it. For "
            "browsing off-screen content in a page or scrollable region, use "
            "Scroll instead. Choose exactly one movement form: (1) relative "
            'swipe — provide "direction" and a positive "distance"; or '
            '(2) endpoint swipe — provide "end". "start" is optional for both '
            "forms and defaults to the center of the page. Do not combine "
            '"end" with "direction" or "distance".'
        )
    return DeviceAction(
        name="Swipe",
        description=description,
        param_schema={
            "start": {
                "type": "locate",
                "description": (
                    f"Optional starting point of the {movement} movement. "
                    "Available in both relative and endpoint forms. If omitted, "
                    "the center of the page is used."
                ),
                "optional": True,
            },
            "direction": {
                "type": '"up" | "down" | "left" | "right"',
                "description": (
                    f"{movement.capitalize()} movement direction. Quick "
                    f"mapping: move the {movement} or content upward -> "
                    '"up"; downward -> "down"; leftward -> "left"; rightward '
                    '-> "right". Required together with a positive distance '
                    "for a relative swipe. Omit when using end."
                ),
                "optional": True,
            },
            "distance": {
                "type": "number",
                "description": (
                    f"Positive length of the {movement} movement in pixels. "
                    "Required together with direction for a relative swipe. "
                    "Omit when using end."
                ),
                "optional": True,
            },
            "end": {
                "type": "locate",
                "description": (
                    f"Endpoint of the {movement} movement. Use for an endpoint "
                    "swipe, optionally with start. Do not provide direction or "
                    "distance when using end."
                ),
                "optional": True,
            },
            "duration": {
                "type": "number",
                "description": "Duration of the swipe gesture in milliseconds",
                "optional": True,
            },
            "repeat": {
                "type": "number",
                "description": (
                    "The number of times to repeat the swipe gesture. 1 for "
                    "default, 0 for continuous mode capped at 10 repeats"
                ),
                "optional": True,
            },
        },
        locate_fields=["start", "end"],
        distance_fields=["distance"],
        sample={
            "start": {"prompt": "center of the notification"},
            "end": {"prompt": "upper edge of the screen"},
        },
        interface_alias="aiSwipe",
        primitive="swipe",
        execute=_execute_swipe,
    )


def _pull_gesture_action() -> DeviceAction:
    """Android-only pull-to-refresh / pull-up action (upstream PullGesture)."""
    return DeviceAction(
        name="PullGesture",
        description="Trigger pull down to refresh or pull up actions",
        param_schema={
            "direction": {
                "type": '"up" | "down"',
                "description": "The direction to pull",
            },
            "distance": {
                "type": "number",
                "description": "The distance to pull (in pixels)",
                "optional": True,
            },
            "duration": {
                "type": "number",
                "description": "The duration of the pull (in milliseconds)",
                "optional": True,
            },
            "locate": {
                "type": "locate",
                "description": "The element to start the pull from (optional)",
                "optional": True,
            },
        },
        locate_fields=["locate"],
        distance_fields=["distance"],
        sample={
            "direction": "down",
            "locate": {"prompt": "the center of the content list area"},
        },
        primitive="pull_gesture",
        execute=_execute_pull_gesture,
    )


def _long_press_action() -> DeviceAction:
    """LongPress is exposed by the touch devices that implement long_press."""
    return DeviceAction(
        name="LongPress",
        description="Long press the element",
        param_schema={
            "locate": {
                "type": "locate",
                "description": "The element to long press",
            },
            "duration": {
                "type": "number",
                "description": "Press duration in milliseconds",
                "optional": True,
            },
        },
        locate_fields=["locate"],
        sample={"locate": {"prompt": "the chat message to react to"}},
        interface_alias="aiLongPress",
        primitive="long_press",
        execute=_execute_long_press,
    )


def build_android_action_space() -> list[DeviceAction]:
    """Android action space: only primitives the device interface implements."""
    actions = [
        action
        for action in build_web_action_space()
        if action.name in _ANDROID_SHARED_ACTIONS
    ]
    actions.extend(
        [
            _swipe_action(),
            _pull_gesture_action(),
            _long_press_action(),
            DeviceAction(
                name="AndroidBackButton",
                supported_by_system_one=True,
                description='Trigger the system "back" operation on Android devices',
                interface_alias="aiAndroidBack",
                primitive="back",
                execute=_make_system_action("back"),
            ),
            DeviceAction(
                name="AndroidHomeButton",
                supported_by_system_one=True,
                description='Trigger the system "home" operation on Android devices',
                interface_alias="aiAndroidHome",
                primitive="home",
                execute=_make_system_action("home"),
            ),
            DeviceAction(
                name="AndroidRecentAppsButton",
                supported_by_system_one=True,
                description='Trigger the system "recent apps" operation on Android devices',
                interface_alias="aiAndroidRecentApps",
                primitive="recent",
                execute=_make_system_action("recent"),
            ),
            DeviceAction(
                name="RunAdbShell",
                description="Run an adb shell command on the device",
                param_schema={
                    "command": {
                        "type": "string",
                        "description": "The adb shell command to run",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Command timeout in milliseconds",
                        "optional": True,
                    },
                },
                locate_fields=[],
                sample={"command": "dumpsys window | grep mCurrentFocus"},
                interface_alias="runAdbShell",
                execute=_execute_run_adb_shell,
            ),
            DeviceAction(
                name="Launch",
                description="Launch an Android app or URL",
                param_schema={
                    "uri": {
                        "type": "string",
                        "description": "App package name or URL to launch",
                    }
                },
                locate_fields=[],
                sample={"uri": "com.example.app"},
                interface_alias="launch",
                execute=_execute_launch,
            ),
            DeviceAction(
                name="Terminate",
                description="Terminate (force-stop) an Android app by package name",
                param_schema={
                    "uri": {
                        "type": "string",
                        "description": "Package name of the app to force-stop",
                    }
                },
                locate_fields=[],
                sample={"uri": "com.example.app"},
                interface_alias="terminate",
                execute=_execute_terminate,
            ),
        ]
    )
    return actions


def _build_harmony_action_space() -> list[DeviceAction]:
    """Harmony action space: mobile set plus system buttons and HDC shell
    (upstream packages/harmony/src/device.ts systemActions). Keyboard combos
    are unsupported on HarmonyOS uitest."""
    harmony_system = [
        DeviceAction(
            name="RunHdcShell",
            description="Execute HDC shell command on HarmonyOS device",
            param_schema={
                "command": {
                    "type": "string",
                    "description": "The shell command to run, without an hdc prefix",
                }
            },
            locate_fields=[],
            sample={"command": "hidumper -s WindowManagerService -a"},
            interface_alias="runHdcShell",
            execute=_execute_run_hdc_shell,
        ),
        DeviceAction(
            name="Launch",
            description="Launch a HarmonyOS app or URL",
            param_schema={
                "uri": {"type": "string", "description": "Bundle name or URL to launch"}
            },
            locate_fields=[],
            sample={"uri": "com.example.app"},
            interface_alias="launch",
            execute=_execute_launch,
        ),
        DeviceAction(
            name="Terminate",
            description="Terminate (force-stop) a HarmonyOS app by bundle name",
            param_schema={
                "uri": {
                    "type": "string",
                    "description": "Bundle name of the app to force-stop",
                }
            },
            locate_fields=[],
            sample={"uri": "com.example.app"},
            interface_alias="terminate",
            execute=_execute_terminate,
        ),
        DeviceAction(
            name="HarmonyBackButton",
            supported_by_system_one=True,
            description='Trigger the system "back" operation on HarmonyOS devices',
            interface_alias="harmonyBack",
            execute=_make_harmony_system_action("back"),
        ),
        DeviceAction(
            name="HarmonyHomeButton",
            supported_by_system_one=True,
            description='Trigger the system "home" operation on HarmonyOS devices',
            interface_alias="harmonyHome",
            execute=_make_harmony_system_action("home"),
        ),
        DeviceAction(
            name="HarmonyRecentAppsButton",
            supported_by_system_one=True,
            description='Trigger the system "recent apps" operation on HarmonyOS devices',
            interface_alias="harmonyRecentApps",
            execute=_make_harmony_system_action("recent_apps"),
        ),
    ]
    mobile = [
        action
        for action in build_web_action_space()
        if action.name not in ("Pinch", "RightClick", "MiddleClick")
    ]
    return mobile + harmony_system


def _build_ios_action_space() -> list[DeviceAction]:
    """iOS action space (upstream packages/ios/src/device.ts actionSpace()):
    the touch-mobile set plus the WDA-specific actions. Mouse-only actions are
    absent because a touch screen has no pointer buttons; ClearInput is
    available because WDA exposes the W3C element clear API."""
    ios_specific = [
        _swipe_action(),
        _long_press_action(),
        DeviceAction(
            name="Launch",
            description="Launch an iOS app or URL",
            param_schema={
                "uri": {
                    "type": "string",
                    "description": "Bundle ID or URL to launch",
                }
            },
            locate_fields=[],
            sample={"uri": "com.apple.Preferences"},
            interface_alias="launch",
            execute=_execute_launch,
        ),
        DeviceAction(
            name="Terminate",
            description="Terminate (close) an iOS app by its bundle ID",
            param_schema={
                "uri": {
                    "type": "string",
                    "description": "Bundle ID of the app to close",
                }
            },
            locate_fields=[],
            sample={"uri": "com.apple.Preferences"},
            interface_alias="terminate",
            execute=_execute_terminate,
        ),
        DeviceAction(
            name="IOSHomeButton",
            supported_by_system_one=True,
            description='Trigger the system "home" operation on iOS devices',
            interface_alias="aiIOSHome",
            primitive="home",
            execute=_make_system_action("home"),
        ),
        DeviceAction(
            name="IOSAppSwitcher",
            supported_by_system_one=True,
            description='Trigger the system "app switcher" operation on iOS devices',
            interface_alias="aiIOSAppSwitcher",
            primitive="app_switcher",
            execute=_make_system_action("app_switcher"),
        ),
        DeviceAction(
            name="RunWdaRequest",
            description="Execute a WebDriverAgent API request on the iOS device",
            param_schema={
                "method": {
                    "type": '"GET" | "POST" | "DELETE" | "PUT"',
                    "description": "HTTP method",
                },
                "endpoint": {
                    "type": "string",
                    "description": "WebDriver API endpoint",
                },
                "data": {
                    "type": "object",
                    "description": "Optional request body data as JSON object",
                    "optional": True,
                },
            },
            locate_fields=[],
            sample={"method": "GET", "endpoint": "/status"},
            interface_alias="runWdaRequest",
            execute=_execute_run_wda_request,
        ),
    ]
    mobile = [
        action
        for action in build_web_action_space()
        if action.name not in ("RightClick", "MiddleClick", "Hover", "DragAndDrop")
    ]
    return mobile + ios_specific


def build_action_space_for(interface_type: str) -> list[DeviceAction]:
    if interface_type == "android":
        return build_android_action_space()
    if interface_type == "harmony":
        return _build_harmony_action_space()
    if interface_type == "ios":
        return _build_ios_action_space()
    # web and computer share the desktop-style action space; Pinch (two-finger
    # touch) is only available on the web touch surface.
    if interface_type == "computer":
        # Upstream computer exposes the pointer swipe but no longPress
        # primitive.
        # TODO(computer): ComputerDevice.long_press stays a direct-API helper
        # until upstream advertises LongPress for this platform.
        return [a for a in build_web_action_space() if a.name != "Pinch"] + [
            _swipe_action("pointer")
        ]
    if interface_type == "web":
        # Upstream web integration exposes the pointer swipe; the Playwright page
        # implements it as a mouse drag with an explicit duration.
        return build_web_action_space() + [_swipe_action("pointer")]
    return build_web_action_space()
