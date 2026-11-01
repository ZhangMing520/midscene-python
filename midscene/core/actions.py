"""Device action space.

Synced from upstream packages/core/src/device/index.ts (web subset) with the
param schemas pre-declared as plain dicts (upstream derives them from zod).
Each action binds to device primitives exposed by the platform interface.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .types import supports_interface_extension

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


def _supported_kwargs(method: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keyword arguments the platform primitive does not accept."""
    import inspect

    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


def input_options(param: Dict[str, Any]) -> Dict[str, Any]:
    """Typing options forwarded to the device input primitive."""
    options: Dict[str, Any] = {}
    if param.get("keyboardTypeDelay") is not None:
        options["keyboard_type_delay"] = param["keyboardTypeDelay"]
    if param.get("inputStrategy") is not None:
        options["input_strategy"] = param["inputStrategy"]
    return options


def _scroll_supported_kwargs(device: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _supported_kwargs(device.scroll, kwargs)


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


async def _execute_swipe(param: Dict[str, Any], device: Any, locate_fn) -> None:
    direction = param.get("direction") or "up"
    distance = param.get("distance")
    if _supports(device, "swipe"):
        await device.swipe(direction, distance=distance)
    else:
        await device.scroll(direction, distance=distance)


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
                "Pinch (two-finger zoom) on the element: direction 'out' zooms "
                "out (fingers move together), 'in' zooms in (fingers move apart)"
            ),
            param_schema={
                "direction": {
                    "type": '"in" | "out"',
                    "description": "Zoom direction",
                },
                "locate": {
                    "type": "locate",
                    "description": "The element to pinch on",
                    "optional": True,
                },
                "distance": {
                    "type": "number",
                    "description": "Pinch distance in pixels",
                    "optional": True,
                },
                "duration": {
                    "type": "number",
                    "description": "Pinch duration in milliseconds",
                    "optional": True,
                },
            },
            locate_fields=["locate"],
            sample={"direction": "in", "locate": {"prompt": "the map"}},
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
                "For direct gesture interactions, use Swipe instead if available. "
                "Default: direction `down`, scrollType `singleAction`, distance `null`."
            ),
            param_schema={
                "scrollType": {
                    "type": '"singleAction" | "scrollToBottom" | "scrollToTop" | "scrollToRight" | "scrollToLeft"',
                    "description": "The scroll behavior. Default: singleAction",
                    "optional": True,
                },
                "direction": {
                    "type": '"down" | "up" | "right" | "left"',
                    "description": "The direction toward the off-screen content to reveal. Default: down",
                    "optional": True,
                },
                "distance": {
                    "type": "number",
                    "description": "Positive requested scroll amount in pixels",
                    "optional": True,
                },
                "locate": {
                    "type": "locate",
                    "description": "The target element to be scrolled on",
                    "optional": True,
                },
            },
            locate_fields=["locate"],
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
    ]


async def _execute_run_adb_shell(param: Dict[str, Any], device: Any, locate_fn) -> None:
    command = param.get("command")
    if not command:
        raise ValueError("RunAdbShell requires a command parameter")
    if not hasattr(device, "run_adb_shell"):
        raise NotImplementedError("RunAdbShell is not supported on this interface")
    timeout = param.get("timeout")
    if timeout is not None:
        await device.run_adb_shell(str(command), timeout=float(timeout))
    else:
        await device.run_adb_shell(str(command))


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


def _make_system_action(method_name: str) -> Callable[..., Any]:
    async def execute(param: Dict[str, Any], device: Any, locate_fn) -> None:
        await getattr(device, method_name)()

    return execute


_ANDROID_SHARED_ACTIONS = (
    "Tap",
    "Input",
    "KeyboardPress",
    "Scroll",
    "ClearInput",
    "DragAndDrop",
    "Sleep",
)


def _swipe_action() -> DeviceAction:
    """Swipe is exposed by touch (android) and pointer (computer) devices."""
    return DeviceAction(
        name="Swipe",
        description=(
            "Perform a swipe gesture with the finger-movement convention: "
            "direction refers to finger movement."
        ),
        param_schema={
            "direction": {
                "type": '"up" | "down" | "left" | "right"',
                "description": "The direction of the finger movement",
            },
            "distance": {
                "type": "number",
                "description": "Swipe distance in pixels",
                "optional": True,
            },
        },
        locate_fields=[],
        sample={"direction": "up", "distance": 400},
        interface_alias="aiSwipe",
        primitive="swipe",
        execute=_execute_swipe,
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
            DeviceAction(
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
            ),
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


def build_action_space_for(interface_type: str) -> List[DeviceAction]:
    if interface_type == "android":
        return build_android_action_space()
    # web and computer share the desktop-style action space; Pinch (two-finger
    # touch) is only available on the web touch surface.
    if interface_type == "computer":
        # Upstream computer exposes the pointer swipe but no longPress
        # primitive.
        # TODO(computer): DesktopDevice.long_press stays a direct-API helper
        # until upstream advertises LongPress for this platform.
        return [
            a for a in build_web_action_space() if a.name != "Pinch"
        ] + [_swipe_action()]
    return build_web_action_space()
