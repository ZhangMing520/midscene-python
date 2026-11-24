"""Shared helpers for web page interfaces (upstream web-integration/web-page.ts)."""

import asyncio
import inspect
import re
import sys
from typing import Any, Protocol

from midscene.core.device import (
    DeviceAction,
    define_actions_from_input_primitives,
)
from midscene.core.device.input_strategy import resolve_text_input_options

_IS_MAC = sys.platform == "darwin"

# upstream web-page.ts getKeyCommands(): the Chrome extension drives CDP
# Input.dispatchKeyEvent, which needs {key, command} objects, not the
# Playwright-style keyName strings the rest of the SDK uses.
_KEY_ALIASES = {
    "return": "Enter",
    "enter": "Enter",
    "command": "Meta",
    "cmd": "Meta",
    "meta": "Meta",
    "shift": "Shift",
    "alt": "Alt",
    "option": "Alt",
    "space": " ",
    "page down": "PageDown",
    "pagedown": "PageDown",
    "page up": "PageUp",
    "pageup": "PageUp",
}

_KEY_ALIASES["ctrl"] = "Meta" if _IS_MAC else "Control"

# Canonical names recognised by upstream getKeyDefinition(): any lowercased
# match returns the canonical spelling (e.g. "escape" -> "Escape").
_NAMED_KEYS = frozenset(
    {
        "Backspace",
        "Tab",
        "Enter",
        "NumpadEnter",
        "Shift",
        "ShiftLeft",
        "ShiftRight",
        "Control",
        "ControlLeft",
        "ControlRight",
        "Meta",
        "MetaLeft",
        "MetaRight",
        "Alt",
        "AltLeft",
        "AltRight",
        "Pause",
        "CapsLock",
        "Escape",
        "Space",
        "PageUp",
        "PageDown",
        "End",
        "Home",
        "ArrowLeft",
        "ArrowUp",
        "ArrowRight",
        "ArrowDown",
        "Select",
        "PrintScreen",
        "Insert",
        "Delete",
        "Semicolon",
        "Equal",
        "Comma",
        "Minus",
        "Period",
        "Slash",
        "Backquote",
        "BracketLeft",
        "Backslash",
        "BracketRight",
        "Quote",
    }
)

_PRIMARY_MODIFIERS = ("Control", "Meta")

_EDIT_COMMANDS = {
    "a": "SelectAll",
    "c": "Copy",
    "v": "Paste",
}


def _get_key_definition(key: str) -> str:
    """Normalize one key token like upstream getKeyDefinition()."""
    lowered = key.lower()
    for canonical in _NAMED_KEYS:
        if canonical.lower() == lowered:
            return canonical
    if len(key) == 1 and key.isalpha():
        return key.upper()
    return key


def _transform_hotkey_input(key_input: str) -> list[str]:
    """Expand aliases and normalize key names (upstream transformHotkeyInput)."""
    lowered = key_input.lower()
    whole_phrase = _KEY_ALIASES.get(lowered)
    if whole_phrase is not None:
        return [_get_key_definition(whole_phrase)]
    return [
        _get_key_definition(_KEY_ALIASES.get(token.lower(), token))
        for token in key_input.split(" ")
    ]


def _normalize_key_inputs(value: str | list[str]) -> list[str]:
    inputs = value if isinstance(value, list) else [value]
    result: list[str] = []

    for item in inputs:
        if not isinstance(item, str):
            result.append(item)
            continue

        trimmed = item.strip()
        if not trimmed:
            result.append(item)
            continue

        normalized = trimmed
        if len(normalized) > 1 and "+" in normalized:
            normalized = re.sub(r"\s*\+\s*", " ", normalized)
        if re.search(r"\s", normalized):
            normalized = re.sub(r"\s+", " ", normalized)

        transformed = _transform_hotkey_input(normalized)
        if len(transformed) == 1 and transformed[0] == "" and trimmed != "":
            result.append(item)
            continue
        if len(transformed) == 0:
            result.append(item)
            continue

        result.extend(transformed)

    return result


def get_key_commands(
    value: str | list[str],
) -> list[dict[str, Any]]:
    """Expand a key or key list into ``{key, command?}`` objects."""
    keys = _normalize_key_inputs(value)
    include_meta = "Meta" in keys or "Control" in keys
    commands: list[dict[str, Any]] = []
    for key in keys:
        command = _EDIT_COMMANDS.get(key.lower()) if include_meta else None
        commands.append({"key": key, "command": command} if command else {"key": key})
    return commands


def build_key_commands(key_name: str) -> list[dict[str, Any]]:
    """Historical single-key wrapper around :func:`get_key_commands`."""
    return get_key_commands(key_name)


class AbstractWebPage(Protocol):
    """Type-level shape of a web page (upstream AbstractWebPage).

    Method bodies are intentionally empty: this protocol documents the
    optional surface consumed by :func:`create_web_input_primitives` and
    :func:`common_web_actions_for_web_page`.
    """

    keyboard_type_delay: float | None
    input_strategy: str | None

    async def navigate(self, url: str) -> None: ...

    async def reload(self) -> None: ...

    async def go_back(self) -> None: ...

    async def go_forward(self) -> None: ...

    async def stop_loading(self) -> None: ...

    async def navigation_state(self) -> dict[str, Any]: ...

    async def flush_pending_visual_update(self, force: bool = False) -> None: ...

    def schedule_pending_visual_update(self, force: bool = False) -> None: ...

    async def wait_for_dom_quiet(
        self, options: dict[str, Any] | None = None
    ) -> None: ...

    async def clear_input(self, element: Any = None) -> None: ...

    async def select_all_input(self, element: Any = None) -> None: ...

    async def scroll_until_top(self, starting_point: Any = None) -> None: ...

    async def scroll_until_bottom(self, starting_point: Any = None) -> None: ...

    async def scroll_until_left(self, starting_point: Any = None) -> None: ...

    async def scroll_until_right(self, starting_point: Any = None) -> None: ...

    async def scroll_up(
        self, distance: float | None = None, starting_point: Any = None
    ) -> None: ...

    async def scroll_down(
        self, distance: float | None = None, starting_point: Any = None
    ) -> None: ...

    async def scroll_left(
        self, distance: float | None = None, starting_point: Any = None
    ) -> None: ...

    async def scroll_right(
        self, distance: float | None = None, starting_point: Any = None
    ) -> None: ...

    async def long_press(
        self, x: float, y: float, duration: float | None = None
    ) -> None: ...

    async def swipe(
        self, from_point: Any, to_point: Any, duration: float | None = None
    ) -> None: ...

    async def pinch(
        self,
        center_x: float,
        center_y: float,
        start_distance: float,
        end_distance: float,
        duration: float | None = None,
    ) -> None: ...


async def _invoke(fn: Any, *args: Any, **kwargs: Any) -> Any:
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _accepts_positional(fn: Any) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        for parameter in signature.parameters.values()
    )


def _accepts_keyword(fn: Any, name: str) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


async def _schedule_web_visual_update(page: Any, force: bool = False) -> None:
    """Mirror upstream scheduleWebVisualUpdate (schedule wins over flush)."""
    schedule = getattr(page, "schedule_pending_visual_update", None)
    if callable(schedule):
        if force:
            schedule(True)
        else:
            schedule()
        return

    flush = getattr(page, "flush_pending_visual_update", None)
    if callable(flush):
        try:
            if force:
                await _invoke(flush, True)
            else:
                await _invoke(flush)
        except Exception:
            pass


def _point_to_xy(point: Any) -> tuple:
    if isinstance(point, dict):
        return point.get("x", 0), point.get("y", 0)
    return point[0], point[1]


def create_web_input_primitives(page: Any) -> dict[str, Any]:
    """Build the low-level browser input primitives for a web page."""

    async def tap(point: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        await page.mouse.click(x, y, button="left")
        await _schedule_web_visual_update(page)

    async def middle_click(point: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        await page.mouse.click(x, y, button="middle")
        await _schedule_web_visual_update(page)

    async def right_click(point: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        await page.mouse.click(x, y, button="right")
        await _schedule_web_visual_update(page)

    async def double_click(point: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        double_click_fn = getattr(page.mouse, "dblclick", None)
        if callable(double_click_fn):
            await _invoke(double_click_fn, x, y)
        else:
            await page.mouse.click(x, y, button="left", count=2)
        await _schedule_web_visual_update(page)

    async def hover(point: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        await page.mouse.move(x, y)
        await _schedule_web_visual_update(page)

    async def drag_and_drop(from_point: Any, to_point: Any) -> None:
        drag_fn = getattr(page.mouse, "drag", None)
        if callable(drag_fn):
            from_xy = _point_to_xy(from_point)
            to_xy = _point_to_xy(to_point)
            await _invoke(
                drag_fn,
                {"x": from_xy[0], "y": from_xy[1]},
                {"x": to_xy[0], "y": to_xy[1]},
            )
        else:
            await _invoke(
                page.drag_and_drop, _point_to_xy(from_point), _point_to_xy(to_point)
            )
        await _schedule_web_visual_update(page)

    async def long_press(
        point: dict[str, Any], opts: dict[str, Any] | None = None
    ) -> None:
        x, y = _point_to_xy(point)
        duration = (opts or {}).get("duration")
        long_press_fn = getattr(page, "long_press", None)
        if callable(long_press_fn):
            await _invoke(long_press_fn, x, y, duration)
        else:
            await page.mouse.move(x, y)
            await page.mouse.down()
            try:
                await asyncio.sleep((duration or 500) / 1000)
            finally:
                await page.mouse.up()
        await _schedule_web_visual_update(page)

    async def type_text(value: str, opts: dict[str, Any] | None = None) -> None:
        options = opts or {}
        element = options.get("target")
        focus_only = bool(options.get("focusOnly"))
        replace = options.get("replace") is not False
        resolved = resolve_text_input_options(options, page)
        input_strategy = resolved["input_strategy"]
        keyboard_type_delay = resolved["keyboard_type_delay"]

        if element and replace:
            if input_strategy == "bulk":
                select_all = getattr(page, "select_all_input", None)
                if callable(select_all):
                    if _accepts_positional(select_all):
                        await _invoke(select_all, element)
                    else:
                        await _invoke(select_all)
                elif callable(getattr(page, "keyboard", None)):
                    await page.keyboard.press("Control+A")
            else:
                clear_input_fn = getattr(page, "clear_input", None)
                if callable(clear_input_fn):
                    if _accepts_positional(clear_input_fn):
                        await _invoke(clear_input_fn, element)
                    else:
                        await _invoke(clear_input_fn)
                await _maybe_wait_for_dom_quiet(page, element)
        elif element and focus_only:
            center = getattr(element, "center", None) or (
                element.get("center") if isinstance(element, dict) else None
            )
            if center:
                await page.mouse.click(center[0], center[1], button="left")
            await page.keyboard.press([{"key": "End"}])
        elif not element and replace and not focus_only:
            select_all = getattr(page, "select_all_input", None)
            if callable(select_all):
                await _invoke(select_all)

        if focus_only:
            return

        if input_strategy == "bulk":
            await page.keyboard.insert_text(value)
        elif input_strategy == "sequential":
            for index, character in enumerate(list(value)):
                await page.keyboard.type(character, delay=0)
                if (
                    keyboard_type_delay
                    and keyboard_type_delay > 0
                    and index < len(list(value)) - 1
                ):
                    await asyncio.sleep(keyboard_type_delay / 1000)
        else:
            if keyboard_type_delay is None:
                await page.keyboard.type(value)
            else:
                await page.keyboard.type(value, delay=keyboard_type_delay)
        await _schedule_web_visual_update(page)

    async def keyboard_press(
        key_name: str | list[str],
        opts: dict[str, Any] | None = None,
    ) -> None:
        element = (opts or {}).get("target")
        if element:
            center = getattr(element, "center", None) or (
                element.get("center") if isinstance(element, dict) else None
            )
            if center:
                await page.mouse.click(center[0], center[1], button="left")
        keys = get_key_commands(key_name)
        await page.keyboard.press(keys)
        await _schedule_web_visual_update(page)

    async def cursor_move(direction: str, times: int = 1) -> None:
        arrow_key = "ArrowLeft" if direction == "left" else "ArrowRight"
        for _ in range(int(times)):
            await page.keyboard.press([{"key": arrow_key}])
            await asyncio.sleep(0.1)

    async def clear_input(target: Any = None) -> None:
        clear_input_fn = getattr(page, "clear_input", None)
        if callable(clear_input_fn):
            if target is not None and _accepts_positional(clear_input_fn):
                await _invoke(clear_input_fn, target)
            else:
                await _invoke(clear_input_fn)

    async def pinch(point: dict[str, Any], opts: dict[str, Any]) -> None:
        x, y = _point_to_xy(point)
        await _invoke(
            page.pinch,
            [x, y],
            opts.get("startDistance"),
            opts.get("endDistance"),
            opts.get("duration"),
        )

    async def swipe(
        from_point: Any, to_point: Any, opts: dict[str, Any] | None = None
    ) -> None:
        duration = (opts or {}).get("duration")
        swipe_points = getattr(page, "swipe_points", None)
        if callable(swipe_points):
            await _invoke(
                swipe_points,
                list(_point_to_xy(from_point)),
                list(_point_to_xy(to_point)),
                duration,
            )
        elif callable(getattr(page, "swipe", None)):
            await _invoke(page.swipe, from_point, to_point, duration)

    async def scroll(param: dict[str, Any] | None = None) -> None:
        param = param or {}
        element = param.get("locate")
        center = None
        if element is not None:
            center = getattr(element, "center", None) or (
                element.get("center") if isinstance(element, dict) else None
            )
        scroll_type = param.get("scrollType")
        if scroll_type in (
            "scrollToTop",
            "scrollToBottom",
            "scrollToRight",
            "scrollToLeft",
        ):
            await _invoke(
                page.scroll,
                scroll_type[len("scrollTo") :].lower(),
                None,
                scroll_type=scroll_type,
                point=center,
            )
        elif scroll_type in ("singleAction", None, ""):
            direction = param.get("direction") or "down"
            if direction not in ("up", "down", "left", "right"):
                raise ValueError(f"Unknown scroll direction: {direction}")
            await _invoke(
                page.scroll,
                direction,
                param.get("distance"),
                point=center,
                scroll_type="singleAction",
            )
            await asyncio.sleep(0.5)
        else:
            raise ValueError(
                f"Unknown scroll event type: {scroll_type}, param: {param}"
            )
        await _schedule_web_visual_update(page)

    return {
        "pointer": {
            "tap": tap,
            "middleClick": middle_click,
            "rightClick": right_click,
            "doubleClick": double_click,
            "hover": hover,
            "dragAndDrop": drag_and_drop,
            "longPress": long_press,
        },
        "keyboard": {
            "typeText": type_text,
            "keyboardPress": keyboard_press,
            "cursorMove": cursor_move,
            "clearInput": clear_input,
        },
        "touch": {
            "pinch": pinch,
            "swipe": swipe,
        },
        "scroll": {"scroll": scroll},
    }


async def _maybe_wait_for_dom_quiet(page: Any, element: Any) -> None:
    wait = getattr(page, "wait_for_dom_quiet", None)
    if not callable(wait):
        return
    try:
        if _accepts_keyword(wait, "target"):
            await _invoke(wait, target=element)
        elif _accepts_positional(wait):
            await _invoke(wait, {"target": element})
        else:
            await _invoke(wait)
    except Exception:
        # Upstream uses optional chaining and ignores a transient DOM check.
        pass


def _navigation_action(
    page: Any,
    *,
    name: str,
    description: str,
    method_name: str,
    param_schema: dict[str, Any] | None = None,
    sample: dict[str, Any] | None = None,
    interface_alias: str | None = None,
    supported_by_system_one: bool = False,
) -> DeviceAction:
    async def execute(
        param: dict[str, Any] | None = None,
        device: Any = None,
        locate_fn: Any = None,
    ) -> None:
        method = getattr(page, method_name, None)
        if not callable(method) and method_name == "navigate":
            method = getattr(page, "navigate_to", None)
        if not callable(method):
            raise ValueError(f"{name} operation is not supported on this page type")
        if param and param.get("url") is not None:
            await _invoke(method, param["url"])
        else:
            await _invoke(method)
        await _schedule_web_visual_update(page, force=True)

    return DeviceAction(
        name=name,
        description=description,
        param_schema=param_schema or {},
        locate_fields=[],
        sample=sample,
        interface_alias=interface_alias,
        supported_by_system_one=supported_by_system_one,
        execute=execute,
    )


def common_web_actions_for_web_page(
    page: Any,
    include_touch_events: bool = False,
) -> list[DeviceAction]:
    """Build the web action space from a page's input primitives."""
    input_primitives = create_web_input_primitives(page)

    def page_size() -> Any:
        return page.size()

    actions = define_actions_from_input_primitives(
        input_primitives,
        {
            "size": page_size,
            "include_swipe": include_touch_events,
        },
    )

    actions.append(
        _navigation_action(
            page,
            name="Navigate",
            description=(
                "Navigate the browser to a specified URL. Opens the URL in "
                "the current tab."
            ),
            method_name="navigate",
            param_schema={
                "url": {
                    "type": "string",
                    "description": (
                        "The URL to navigate to. Must start with https://, "
                        "file://, or a similar protocol."
                    ),
                }
            },
            sample={"url": "https://www.example.com"},
            interface_alias="aiNavigate",
        )
    )
    actions.append(
        _navigation_action(
            page,
            name="Reload",
            description="Reload the current page",
            method_name="reload",
            interface_alias="aiReload",
            supported_by_system_one=True,
        )
    )
    actions.append(
        _navigation_action(
            page,
            name="GoBack",
            description="Navigate back in browser history",
            method_name="go_back",
            interface_alias="aiGoBack",
            supported_by_system_one=True,
        )
    )
    actions.append(
        _navigation_action(
            page,
            name="GoForward",
            description="Navigate forward in browser history",
            method_name="go_forward",
            interface_alias="aiGoForward",
            supported_by_system_one=True,
        )
    )
    return actions


__all__ = [
    "AbstractWebPage",
    "build_key_commands",
    "common_web_actions_for_web_page",
    "create_web_input_primitives",
    "get_key_commands",
]
