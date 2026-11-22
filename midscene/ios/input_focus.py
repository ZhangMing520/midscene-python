"""iOS input-focus discovery and recovery (upstream ios/src/input-focus.ts).

The transport is injected so callers can share the same logic across the
WebDriverAgent client and any session-relative request surface.
"""

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, List, Optional

from midscene.webdriver import WebDriverRequestError, element_id_from

InputRequest = Callable[
    [str, str, Optional[dict]], Awaitable[dict]
]

TEXT_INPUT_TYPES = (
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeTextView",
    "XCUIElementTypeSearchField",
)


def _is_protocol_error(error: BaseException, code: str) -> bool:
    return isinstance(error, WebDriverRequestError) and error.error_code == code


async def active_input(
    request: InputRequest,
) -> Optional[str]:
    """The id of the focused element, or None when nothing has focus."""
    try:
        response = await request("GET", "/element/active", None)
    except WebDriverRequestError as error:
        if _is_protocol_error(error, "no such element"):
            return None
        raise
    value = response.get("value")
    return None if value is None else element_id_from(value)


async def wait_for_input_focus(
    request: InputRequest, *, timeout_ms: float = 3000.0
) -> None:
    """Block until an element owns the keyboard, or fail loudly."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not await active_input(request):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for iOS input focus after "
                f"{int(timeout_ms)}ms"
            )
        await asyncio.sleep(0.05)


async def _identified_inputs(
    request: InputRequest, name: str, element_type: str
) -> List[str]:
    """Elements whose name is a real identifier and whose type matches.

    WDA falls back to label when the accessibility identifier is empty;
    excluding that case proves the name identifies the field on both the old
    and the current snapshot.
    """
    response = await request(
        "POST",
        "/elements",
        {
            "using": "predicate string",
            "value": (
                f"name == {json.dumps(name)} AND name != label "
                f"AND type == {json.dumps(element_type)}"
            ),
        },
    )
    value = response.get("value")
    if not isinstance(value, list):
        raise RuntimeError("Invalid WDA input search response")
    ids = [element_id_from(item) for item in value]
    if any(element_id is None for element_id in ids):
        raise RuntimeError("Missing WDA input element ID")
    return ids


async def clear_input_with_focus(request: InputRequest) -> bool:
    """Clear the focused input and keep focus.

    Returns False when there is nothing to clear or this WDA build has no
    active-element API, so callers can fall back to plain typing. Raises when
    a clear cannot be verified: appending text to a field still full of the
    old value is worse than reporting failure.
    """
    try:
        original_id = await active_input(request)
    except WebDriverRequestError as error:
        if _is_protocol_error(error, "unknown command") or _is_protocol_error(
            error, "unsupported operation"
        ):
            return False
        raise
    if not original_id:
        return False

    # Re-identification is only a recovery hint: a failed lookup must not stop
    # the clear itself from being attempted.
    name = ""
    element_type: Any = None
    try:
        raw_name = (
            await request(
                "GET", f"/element/{original_id}/attribute/name", None
            )
        ).get("value")
        name = raw_name if isinstance(raw_name, str) else ""
        element_type = (
            await request(
                "GET", f"/element/{original_id}/attribute/type", None
            )
        ).get("value")
    except WebDriverRequestError:
        name = ""
        element_type = None
    is_text_input = (
        isinstance(element_type, str) and element_type in TEXT_INPUT_TYPES
    )
    can_reacquire = False
    if name and is_text_input:
        try:
            named = await _identified_inputs(request, name, element_type)
        except WebDriverRequestError:
            named = []
        can_reacquire = len(named) == 1 and named[0] == original_id
    target_id = original_id

    # One retry is allowed after a stale clear: the field may have been
    # re-created, in which case the retry targets the re-identified id. A
    # successful clear response proves the operation completed without
    # guessing whether the accessibility value is text or placeholder text.
    retries_left = 1
    while True:
        clear_error: Optional[BaseException] = None
        try:
            await request("POST", f"/element/{target_id}/clear", None)
        except WebDriverRequestError as error:
            if not _is_protocol_error(error, "stale element reference"):
                raise
            clear_error = error

        if await active_input(request) != target_id:
            try:
                await request("POST", f"/element/{target_id}/click", None)
            except WebDriverRequestError as error:
                if (
                    not _is_protocol_error(error, "stale element reference")
                    or not can_reacquire
                ):
                    raise
                matches = await _identified_inputs(
                    request, name, element_type
                )
                if len(matches) != 1:
                    raise RuntimeError(
                        "Cannot uniquely identify input after clearing the "
                        "field"
                    )
                target_id = matches[0]
                await request("POST", f"/element/{target_id}/click", None)
            if await active_input(request) != target_id:
                raise RuntimeError(
                    "Failed to restore input focus after clearing the field"
                )

        if clear_error is None:
            return True
        value = (
            await request(
                "GET", f"/element/{target_id}/attribute/value", None
            )
        ).get("value")
        if value is None or value == "":
            return True
        if retries_left == 0:
            raise RuntimeError(
                "Cannot verify that input was cleared; refusing to append text"
            ) from clear_error
        retries_left -= 1


__all__ = [
    "TEXT_INPUT_TYPES",
    "active_input",
    "clear_input_with_focus",
    "wait_for_input_focus",
]
