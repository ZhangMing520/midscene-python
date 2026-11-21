"""Device action space.

Synced from upstream packages/core/src/device/index.ts (web subset) with the
param schemas pre-declared as plain dicts (upstream derives them from zod).
Each action binds to device primitives exposed by the platform interface.
"""

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

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
    param_schema: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    locate_fields: List[str] = field(default_factory=list)
    distance_fields: List[str] = field(default_factory=list)
    sample: Optional[Dict[str, Any]] = None
    interface_alias: Optional[str] = None
    supported_by_system_one: bool = False
    primitive: Optional[str] = None  # device method the action requires
    execute: Optional[Callable[..., Any]] = None  # async (param, device, locate_fn)

    def to_prompt_dict(self) -> Dict[str, Any]:
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
    action_type: str, action_space: List[Any]
) -> Any:
    for action in action_space:
        name = action["name"] if isinstance(action, dict) else action.name
        if name == action_type:
            return action
    raise ValueError(
        f"Action type {action_type} not found in action space. "
        f"Available actions: "
        f"{[a['name'] if isinstance(a, dict) else a.name for a in action_space]}"
    )


def scale_action_distances(
    param: Dict[str, Any], definition: Any, ratio: float
) -> Dict[str, Any]:
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


def _swipe_center(locate: Any, name: str) -> Dict[str, float]:
    center = locate.get("center") if isinstance(locate, dict) else None
    if not center or len(center) < 2:
        raise ValueError(f'Swipe "{name}" requires a located center point')
    return {"x": float(center[0]), "y": float(center[1])}


def normalize_swipe_param(
    param: Dict[str, Any], screen_size: Dict[str, Any]
) -> Dict[str, Any]:
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
                'Invalid Swipe parameters: a relative swipe requires both '
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
                else -distance if direction == "left" else 0
            ),
            "y": start_point["y"]
            + (
                distance
                if direction == "down"
                else -distance if direction == "up" else 0
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


# ---------------------------------------------------------------------------
# Action executors. `device` is the platform interface; `locate_fn` resolves a
# locate param ({prompt, locatedPixelResult?}) to {'center': (x, y), 'rect'?}.
# ---------------------------------------------------------------------------

async def _resolve_locate_point(locate_param: Dict[str, Any], locate_fn) -> Dict[str, Any]:
    if not isinstance(locate_param, dict) or not locate_param.get("prompt"):
        raise ValueError("locate parameter requires a prompt")
    return await locate_fn(locate_param)


def _make_tap(executor: str) -> Callable[..., Any]:
    async def execute(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_input(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_keyboard_press(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_scroll(param: Dict[str, Any], device: Any, locate_fn) -> None:
    direction = param.get("direction") or "down"
    distance = param.get("distance")
    scroll_type = param.get("scrollType") or "singleAction"
    kwargs: Dict[str, Any] = {"scroll_type": scroll_type}
    if distance is not None:
        kwargs["distance"] = distance
    locate = param.get("locate")
    if locate is not None:
        point = await _resolve_locate_point(locate, locate_fn)
        kwargs["point"] = point["center"]
    await device.scroll(direction, **_scroll_supported_kwargs(device, kwargs))


async def _execute_clear_input(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_sleep(param: Dict[str, Any], device: Any, locate_fn) -> None:
    time_ms = param.get("timeMs") or 1000
    try:
        time_ms = max(0, min(int(time_ms), 5 * 60 * 1000))
    except (TypeError, ValueError):
        time_ms = 1000
    await asyncio.sleep(time_ms / 1000)


async def _execute_cursor_move(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_navigate(param: Dict[str, Any], device: Any, locate_fn) -> None:
    url = param.get("url")
    if not url or not str(url).strip():
        raise ValueError("Navigate requires a non-empty url parameter")
    if not _supports(device, "navigate_to"):
        raise NotImplementedError("Navigate is not supported on this interface")
    await device.navigate_to(str(url))


async def _execute_reload(param: Dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "reload"):
        raise NotImplementedError("Reload is not supported on this interface")
    await device.reload()


async def _execute_go_back(param: Dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "go_back"):
        raise NotImplementedError("GoBack is not supported on this interface")
    await device.go_back()


async def _execute_go_forward(param: Dict[str, Any], device: Any, locate_fn) -> None:
    if not _supports(device, "go_forward"):
        raise NotImplementedError("GoForward is not supported on this interface")
    await device.go_forward()


async def _resolve_screen_size(device: Any) -> Dict[str, float]:
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


async def _execute_swipe(param: Dict[str, Any], device: Any, locate_fn) -> None:
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

    def _swipe_kwargs() -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"distance": distance}
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
        point_kwargs: Dict[str, Any] = {}
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

    raise NotImplementedError(
        "Swipe endpoint form is not supported on this interface"
    )


async def _execute_drag_and_drop(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


async def _execute_long_press(param: Dict[str, Any], device: Any, locate_fn) -> None:
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


def build_web_action_space() -> List[DeviceAction]:
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
            sample={"direction": "out", "distance": 200,
                    "locate": {"prompt": "the map area"}},
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
            sample={"value": "test@example.com", "locate": {"prompt": "the email input field"}},
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
                        'intermediate content until reaching the bottom), '
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
                        'The direction toward the off-screen content to reveal. '
                        'Quick mapping: want to see content below the current '
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


async def _execute_run_adb_shell(param: Dict[str, Any], device: Any, locate_fn) -> Any:
    command = param.get("command")
    if not command:
        raise ValueError("RunAdbShell requires a command parameter")
    if not hasattr(device, "run_adb_shell"):
        raise NotImplementedError("RunAdbShell is not supported on this interface")
    timeout = param.get("timeout")
    if timeout is not None:
        return await device.run_adb_shell(str(command), timeout=float(timeout))
    return await device.run_adb_shell(str(command))


async def _execute_launch(param: Dict[str, Any], device: Any, locate_fn) -> None:
    uri = param.get("uri")
    if not uri or not str(uri).strip():
        raise ValueError("Launch requires a non-empty uri parameter")
    await device.launch_app(str(uri))


async def _execute_terminate(param: Dict[str, Any], device: Any, locate_fn) -> None:
    uri = param.get("uri")
    if not uri or not str(uri).strip():
        raise ValueError("Terminate requires a non-empty uri parameter")
    await device.stop_app(str(uri))


async def _execute_pinch(param: Dict[str, Any], device: Any, locate_fn) -> None:
    direction = param.get("direction")
    if direction not in ("in", "out"):
        raise ValueError('Pinch direction must be "in" or "out"')
    locate = param.get("locate")
    point = None
    if locate is not None:
        point_result = await _resolve_locate_point(locate, locate_fn)
        point = point_result["center"]
    kwargs: Dict[str, Any] = {}
    if param.get("distance") is not None:
        kwargs["distance"] = param["distance"]
    if param.get("duration") is not None:
        kwargs["duration"] = param["duration"]
    await device.pinch(direction, point=point, **kwargs)


async def _execute_run_hdc_shell(param: Dict[str, Any], device: Any, locate_fn) -> Any:
    command = param.get("command")
    if not command or not str(command).strip():
        raise RuntimeError("RunHdcShell requires a non-empty command")
    if not hasattr(device, "run_hdc_shell"):
        raise NotImplementedError("RunHdcShell is not supported on this interface")
    return await device.run_hdc_shell(str(command))


_WDA_HTTP_METHODS = ("GET", "POST", "DELETE", "PUT")


async def _execute_run_wda_request(param: Dict[str, Any], device: Any, locate_fn) -> Any:
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
    async def execute(param: Dict[str, Any], device: Any, locate_fn) -> None:
        await getattr(device, method_name)()

    return execute


def _make_system_action(method_name: str) -> Callable[..., Any]:
    async def execute(param: Dict[str, Any], device: Any, locate_fn) -> None:
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
            'Scroll instead. Choose exactly one movement form: (1) relative '
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


def build_android_action_space() -> List[DeviceAction]:
    """Android action space: only primitives the device interface implements."""
    actions = [
        action
        for action in build_web_action_space()
        if action.name in _ANDROID_SHARED_ACTIONS
    ]
    actions.extend(
        [
            _swipe_action(),
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


def _build_harmony_action_space() -> List[DeviceAction]:
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


def _build_ios_action_space() -> List[DeviceAction]:
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
        if action.name
        not in ("RightClick", "MiddleClick", "Hover", "DragAndDrop")
    ]
    return mobile + ios_specific


def build_action_space_for(interface_type: str) -> List[DeviceAction]:
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
        return [
            a for a in build_web_action_space() if a.name != "Pinch"
        ] + [_swipe_action("pointer")]
    if interface_type == "web":
        # Upstream web integration exposes the pointer swipe; the Playwright and
        # Selenium pages implement it as a mouse drag with an explicit duration.
        return build_web_action_space() + [_swipe_action("pointer")]
    return build_web_action_space()
