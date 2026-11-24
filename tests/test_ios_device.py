"""Port of upstream packages/ios/tests/unit-test/device.test.ts.

The Python iOS backend talks to WDA through an injectable request callable, so
the upstream mock of ``mockWdaClient`` becomes a fake W3C actions transport.

Only the cases covered by the former aggregate ``tests/test_ios.py`` are kept.
"""

import re
from typing import Any
from unittest.mock import AsyncMock

import pytest

from midscene.core.device import (
    build_action_space_for,
    find_action_in_action_space_or_throw,
)
from midscene.ios.device import IOSDevice
from midscene.ios.wda import WebDriverAgentBackend

SCREEN = (375, 812)


class FakeWDARequests:
    """Session-relative WDA transport used by the device tests."""

    def __init__(self, responses: dict[str, Any] | None = None):
        self.responses = responses or {}
        self.requests: list[tuple] = []
        self._hits: dict[str, int] = {}

    async def __call__(self, method, path, body=None):
        self.requests.append((method, path, body))
        key = re.sub(r"(/session/)[^/]+", r"\1X", f"{method} {path}")
        for pattern, response in self.responses.items():
            normalized = re.sub(r"(/session/)[^/]+", r"\1X", pattern)
            if key.startswith(normalized):
                if isinstance(response, list):
                    index = self._hits.get(pattern, 0)
                    self._hits[pattern] = index + 1
                    response = response[min(index, len(response) - 1)]
                if isinstance(response, Exception):
                    raise response
                return response
        raise RuntimeError(f"Unhandled WDA request: {method} {path}")

    def calls_for(self, fragment: str) -> list[tuple]:
        return [call for call in self.requests if fragment in call[1]]


def _backend(responses: dict[str, Any] | None = None, size=SCREEN) -> tuple:
    backend = WebDriverAgentBackend(base_url="http://localhost:8100")
    transport = FakeWDARequests(
        {
            "GET /session/X/window/rect": {
                "value": {"width": size[0], "height": size[1]}
            },
            **(responses or {}),
            "": {},
        }
    )
    backend.make_request = transport
    backend.session_id = "wda-session"
    backend.owns_session = False
    return backend, transport


def _device(responses=None, size=SCREEN):
    device = IOSDevice()
    backend, transport = _backend(responses, size)
    device.wda = backend
    device._connected = True
    return device, transport


def _pointer_moves(transport: FakeWDARequests) -> list[dict]:
    call = transport.calls_for("/actions")[0]
    actions = call[2]["actions"][0]["actions"]
    return [action for action in actions if action["type"] == "pointerMove"]


def _gesture(transport: FakeWDARequests) -> tuple:
    moves = _pointer_moves(transport)
    first, last = moves[0], moves[-1]
    return (
        first["x"],
        first["y"],
        last["x"],
        last["y"],
        last["duration"],
    )


# -- scroll ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["down", "up", "left", "right"])
async def test_rejects_invalid_scroll_distances_before_sending_any_gesture(
    direction,
):
    """rejects invalid %s distances before sending any gesture."""

    scroll = find_action_in_action_space_or_throw(
        "Scroll", build_action_space_for("ios")
    )

    async def locate(_prompt):
        return {"center": [188, 406]}

    for distance in (0, float("nan"), -1, float("inf"), float("-inf")):
        device, transport = _device()
        with pytest.raises(ValueError, match="positive and finite"):
            await scroll.execute(
                {
                    "direction": direction,
                    "distance": distance,
                    "locate": {"prompt": "list"},
                },
                device,
                locate,
            )
        assert transport.calls_for("/actions") == []


@pytest.mark.asyncio
async def test_keeps_the_default_scroll_when_distance_is_none():
    """keeps the default scroll when distance is null/undefined."""

    device, transport = _device()
    await device.scroll("down", None)

    assert _gesture(transport) == (188, 690, 188, 122, 1420)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction,x,y,expected",
    [
        ("down", 319, 773, (319, 773, 319, 1, 500)),
        ("up", 100, 100, (100, 100, 100, 811, 500)),
        ("left", 100, 400, (100, 400, 374, 400, 500)),
        ("right", 300, 400, (300, 400, 1, 400, 500)),
    ],
)
async def test_keeps_an_oversized_scroll_on_screen_without_moving_its_touch_origin(
    direction, x, y, expected
):
    """keeps an oversized %s scroll on screen without moving its touch origin."""

    scroll = find_action_in_action_space_or_throw(
        "Scroll", build_action_space_for("ios")
    )

    async def locate(_prompt):
        return {"center": [x, y]}

    device, transport = _device()
    await scroll.execute(
        {
            "direction": direction,
            "distance": 1000,
            "locate": {"prompt": "list"},
        },
        device,
        locate,
    )

    assert _gesture(transport) == expected


@pytest.mark.asyncio
async def test_preserves_a_short_scroll_and_its_chosen_origin():
    """preserves a short scroll and its chosen origin.

    The actionable y (773) sits near the bottom edge; the bounded endpoint is
    673, so the gesture neither reverses nor falls back to the viewport centre.
    """

    device, transport = _device()
    await device.scroll("down", 100, point=[319, 773])

    assert _gesture(transport) == (319, 773, 319, 673, 500)


@pytest.mark.asyncio
async def test_rejects_an_off_screen_origin_instead_of_redirecting_the_gesture():
    """rejects an off-screen origin instead of redirecting the gesture."""

    device, transport = _device()
    with pytest.raises(ValueError, match="origin"):
        await device.scroll("down", 100, point=[-1, 400])
    assert transport.calls_for("/actions") == []


@pytest.mark.asyncio
async def test_does_not_reverse_direction_at_the_screen_edge():
    """does not reverse direction at the screen edge."""

    device, transport = _device()
    with pytest.raises(ValueError, match="No room"):
        await device.scroll("down", 100, point=[100, 0])
    assert transport.calls_for("/actions") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,width,from_x,to_x",
    [
        ("scrollUntilLeft", 402, 80, 321),
        ("scrollUntilRight", 402, 322, 81),
        ("scrollUntilLeft", 874, 175, 699),
        ("scrollUntilRight", 874, 699, 175),
    ],
)
async def test_scroll_until_leaves_room_for_a_full_gesture_on_a_viewport(
    method, width, from_x, to_x, monkeypatch
):
    """scrollUntilLeft/Right leaves room for a full gesture on a %i-point viewport."""

    device, transport = _device(size=(width, 900))
    screenshots = iter([f"frame-{index}" for index in range(40)])
    device.screenshot_base64 = _async_value(screenshots)
    monkeypatch.setattr("midscene.ios.device.asyncio.sleep", _async_noop())

    # `scroll` dispatches on scrollType; call the boundary loop directly so the
    # gesture geometry is observable.
    direction = "left" if "Left" in method else "right"
    await device._scroll_until_boundary(direction)

    first = _pointer_moves(transport)[0]
    assert (first["x"], first["y"]) == (from_x, 450)
    assert _gesture(transport) == (from_x, 450, to_x, 450, 300)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction,width,height,expected",
    [
        ("down", 375, 812, (188, 690, 188, 122, 1420)),
        ("up", 375, 812, (188, 122, 188, 690, 1420)),
        ("right", 375, 812, (319, 406, 56, 406, 1000)),
        ("left", 375, 812, (56, 406, 319, 406, 1000)),
        ("down", 812, 375, (406, 319, 406, 56, 1000)),
        ("up", 812, 375, (406, 56, 406, 319, 1000)),
        ("right", 812, 375, (690, 188, 122, 188, 1420)),
        ("left", 812, 375, (122, 188, 690, 188, 1420)),
    ],
)
async def test_uses_bounded_endpoints_and_distance_timing_for_default_scrolls(
    direction, width, height, expected
):
    """%s uses bounded endpoints and at least one second of distance-based timing on %ix%i."""

    device, transport = _device(size=(width, height))
    await device.scroll(direction)

    assert _gesture(transport) == expected


# -- device operations ----------------------------------------------------------


@pytest.mark.asyncio
async def test_should_perform_tap_operation():
    """should perform tap operation."""

    device, transport = _device()
    await device.tap(100, 200)

    call = transport.calls_for("/wda/tap")[0]
    assert call[2] == {"x": 100, "y": 200}


@pytest.mark.asyncio
async def test_should_type_text():
    """should type text."""

    device, transport = _device()
    await device.input_text("hello")

    call = transport.calls_for("/wda/keys")[0]
    assert call[2] == {"value": ["h", "e", "l", "l", "o"]}


@pytest.mark.asyncio
async def test_should_get_screen_size_after_connection():
    """should get screen size after connection."""

    device, _ = _device()
    assert await device.size() == {"width": 375, "height": 812}


@pytest.mark.asyncio
async def test_should_take_screenshot_after_connection():
    """should take screenshot after connection."""

    device, _ = _device({"GET /session/X/screenshot": {"value": "rawbase64"}})

    assert await device.screenshot_base64() == "data:image/png;base64,rawbase64"


@pytest.mark.asyncio
async def test_should_handle_app_launch_with_bundle_id():
    """should handle app launch with bundle ID."""

    device, transport = _device()
    await device.launch_app("com.apple.Preferences")

    call = transport.calls_for("/wda/apps/launch")[0]
    assert call[2] == {"bundleId": "com.apple.Preferences"}


@pytest.mark.asyncio
async def test_should_handle_url_launch_with_http_url():
    """should handle URL launch with HTTP URL."""

    device, transport = _device()
    await device.launch_app("https://www.apple.com")

    call = transport.calls_for("/url")[0]
    assert call[2] == {"url": "https://www.apple.com"}


@pytest.mark.asyncio
async def test_does_not_send_text_when_focus_fails(monkeypatch):
    """does not send text when focus fails (replace=true).

    `clearInputAt` starts by waiting for input focus, so an unfocused device
    must fail before touching the element API or the keys endpoint.
    """

    monkeypatch.setattr("midscene.ios.device.INPUT_FOCUS_TIMEOUT_MS", 0)
    device, transport = _device({"GET /session/X/element/active": {"value": None}})

    with pytest.raises(RuntimeError, match="waiting for iOS input focus"):
        await device.clear_input()

    assert transport.calls_for("/clear") == []
    assert transport.calls_for("/wda/keys") == []


def test_describe_returns_device_id_when_no_description_is_set():
    """returns Device ID when no description is available."""
    device = IOSDevice()

    assert device.describe() == "Device ID: pending-connection"


@pytest.mark.asyncio
async def test_get_connected_device_info_returns_wda_device_metadata():
    """returns the WDA device info."""
    device, _ = _device(
        {
            "GET /status": {
                "device": {
                    "udid": "real-udid",
                    "name": "iPhone",
                    "model": "iPhone15,2",
                }
            }
        }
    )

    info = await device.get_connected_device_info()

    assert info == {
        "udid": "real-udid",
        "name": "iPhone",
        "model": "iPhone15,2",
    }


@pytest.mark.asyncio
async def test_get_screen_size_includes_the_device_pixel_ratio():
    """returns width/height plus the WDA screen scale."""
    device, _ = _device({"GET /session/X/wda/screen": {"value": {"scale": 2}}})

    assert await device.get_screen_size() == {
        "width": 375,
        "height": 812,
        "scale": 2,
    }


@pytest.mark.asyncio
async def test_get_elements_info_and_node_tree_are_empty():
    """returns the upstream empty element representations."""
    device, _ = _device()

    assert await device.get_elements_info() == []
    assert await device.get_elements_node_tree() == {"node": None, "children": []}
    assert await device.url() == ""


@pytest.mark.asyncio
async def test_should_terminate_app_by_bundle_id():
    """should terminate an app by bundle ID."""
    device, transport = _device()
    await device.terminate("com.apple.Preferences")

    call = transport.calls_for("/wda/apps/terminate")[0]
    assert call[2] == {"bundleId": "com.apple.Preferences"}


@pytest.mark.asyncio
async def test_should_open_url_through_launch(monkeypatch):
    """launches URLs through the WDA url endpoint."""
    device, transport = _device()
    monkeypatch.setattr("midscene.ios.device.asyncio.sleep", AsyncMock())
    await device.launch("https://www.apple.com")

    call = transport.calls_for("/url")[0]
    assert call[2] == {"url": "https://www.apple.com"}


@pytest.mark.asyncio
async def test_hide_keyboard_delegates_to_wda(monkeypatch):
    """hideKeyboard delegates to the WDA keyboard dismissal helper."""
    device, _ = _device()
    dismiss = AsyncMock(return_value=True)
    monkeypatch.setattr(device.wda, "dismiss_keyboard", dismiss)

    assert await device.hide_keyboard(["Done"]) is True
    dismiss.assert_awaited_once_with(["Done"])


@pytest.mark.asyncio
async def test_scroll_helpers_delegate_with_direction_distance_and_origin(monkeypatch):
    """scrollUp/Down/Left/Right forward their arguments."""
    device, _ = _device()
    scroll = AsyncMock()
    monkeypatch.setattr(device, "_scroll_in_direction", scroll)

    await device.scroll_down(200, {"left": 10, "top": 20})

    scroll.assert_awaited_once_with("down", 200, [10.0, 20.0])


@pytest.mark.asyncio
async def test_scroll_until_helpers_delegate_with_origin(monkeypatch):
    """scrollUntil* forward the boundary direction and origin."""
    device, _ = _device()
    scroll = AsyncMock()
    monkeypatch.setattr(device, "_scroll_until_boundary", scroll)

    await device.scroll_until_right({"left": 30, "top": 40})

    scroll.assert_awaited_once_with("right", [30.0, 40.0])


@pytest.mark.asyncio
async def test_waits_before_clearing_a_prefilled_field_and_sends_replacement_text_once():
    """waits before clearing a prefilled field and sends replacement text once."""

    focused = {
        "GET /session/X/element/active": {"value": {"ELEMENT": "input"}},
        "GET /session/X/element/input/attribute/name": {"value": "field"},
        "GET /session/X/element/input/attribute/type": {
            "value": "XCUIElementTypeTextField"
        },
        "POST /session/X/element/input/clear": {"value": None},
        "POST /session/X/elements": {"value": [{"ELEMENT": "input"}]},
    }
    device, transport = _device(focused)

    await device.replace_input("new text")

    clear_index = transport.requests.index(
        next(call for call in transport.requests if "/clear" in call[1])
    )
    keys_index = transport.requests.index(
        next(call for call in transport.requests if "/wda/keys" in call[1])
    )
    assert clear_index < keys_index
    keys_calls = transport.calls_for("/wda/keys")
    assert len(keys_calls) == 1
    assert keys_calls[0][2] == {"value": list("new text")}


# -- lifecycle ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_handle_destroy_properly():
    """should handle destroy properly."""

    device, _ = _device()
    await device.destroy()

    assert device._connected is False
    assert device.wda.session_id is None


@pytest.mark.asyncio
async def test_should_handle_multiple_destroy_calls_gracefully():
    """should handle multiple destroy calls gracefully."""

    device, _ = _device()
    await device.destroy()
    await device.destroy()

    assert device._connected is False


# -- helpers --------------------------------------------------------------------


def _async_value(iterator):
    async def value():
        return next(iterator)

    return value


def _async_noop():
    async def noop(*_args, **_kwargs):
        return None

    return noop
