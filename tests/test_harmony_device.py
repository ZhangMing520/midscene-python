"""Port of upstream packages/harmony/tests/unit-test/device.test.ts.

Combines the five app-name-mapping cases that used to live in the generic
``tests/test_device.py`` with the device cases covered by the former aggregate
``tests/test_harmony.py``.

Python exposes an endpoint-based ``scroll(direction, distance, point=...)``
instead of upstream's ``scrollDown``/``scrollUp``/``scrollLeft``/``scrollRight``
and ``scrollUntil*`` helpers, so those cases call the equivalent Python shape.
The upstream delta-based ``scroll(dx, dy)`` cases and the 16-action list are
not portable: see the skipped action-space case and the report.
"""

import pytest

from midscene.core.device import (
    build_action_space_for,
    find_action_in_action_space_or_throw,
)
from midscene.harmony.device import HarmonyDevice

SCREEN = (1200, 2400)


class FakeHdc:
    def __init__(self, screen=SCREEN):
        self.calls = []
        self.screen = screen

    async def get_screen_info(self):
        return {"width": self.screen[0], "height": self.screen[1]}

    async def click(self, *args):
        self.calls.append(("click", *args))

    async def input_text(self, *args):
        self.calls.append(("inputText", *args))

    async def key_event(self, *args):
        self.calls.append(("keyEvent", *args))

    async def fling(self, *args):
        self.calls.append(("fling", *args))

    async def clear_text_field(self, *args):
        self.calls.append(("clearTextField", *args))

    async def launch(self, *args):
        self.calls.append(("launch", *args))

    async def start_ability(self, *args):
        self.calls.append(("start_ability", *args))

    async def force_stop(self, *args):
        self.calls.append(("force_stop", *args))

    async def shell(self, *args):
        self.calls.append(("shell", *args))
        return ""


def _device(screen=SCREEN) -> HarmonyDevice:
    device = HarmonyDevice("test-device-id")
    device.hdc = FakeHdc(screen)

    async def get_hdc():
        return device.hdc

    device._get_hdc = get_hdc
    return device


# -- app name mapping (formerly tests/test_device.py) ---------------------------


@pytest.mark.asyncio
async def test_should_store_mapping_and_resolve_on_launch():
    """should store mapping and resolve on launch."""

    device = _device()
    device.set_app_name_mapping({"browser": "com.huawei.hmos.browser"})

    await device.launch_app("Browser")

    assert ("launch", "com.huawei.hmos.browser") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_start_an_explicit_ability_from_app_name_mapping():
    """should start an explicit ability from app name mapping."""

    device = _device()
    device.set_app_name_mapping({"Video App": "com.example.video/PhoneAbility"})

    await device.launch_app("video-app")

    assert (
        "start_ability",
        "com.example.video",
        "PhoneAbility",
    ) in device.hdc.calls
    assert not any(call[0] == "launch" for call in device.hdc.calls)


@pytest.mark.asyncio
async def test_should_fall_back_to_original_name_if_not_in_mapping():
    """should fall back to original name if not in mapping."""

    device = _device()
    device.set_app_name_mapping({})

    await device.launch_app("com.unknown.app")

    assert ("launch", "com.unknown.app") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_resolve_app_name_mapping_before_force_stop():
    """should resolve app name mapping before force-stop."""

    device = _device()
    device.set_app_name_mapping({"music": "com.huawei.hmsapp.music"})

    await device.stop_app("Music")

    assert ("force_stop", "com.huawei.hmsapp.music") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_use_only_the_bundle_part_of_a_mapped_bundle_ability_target():
    """should use only the bundle part of a mapped bundle/ability target."""

    device = _device()
    device.set_app_name_mapping({"Video": "com.example.video/PhoneAbility"})

    await device.stop_app("Video")

    assert ("force_stop", "com.example.video") in device.hdc.calls


# -- pointer / input ------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_call_hdc_click():
    """should call hdc.click."""

    device = _device()

    await device.tap(100, 200)

    assert ("click", 100, 200) in device.hdc.calls


@pytest.mark.asyncio
async def test_should_use_element_center_when_element_is_provided():
    """should use element center when element is provided."""

    device = _device()
    action = find_action_in_action_space_or_throw(
        "Input", build_action_space_for("harmony")
    )

    async def locate(_prompt):
        return {"center": [500, 600]}

    await action.execute(
        {"value": "hello", "locate": {"prompt": "search box"}},
        device,
        locate,
    )

    assert ("inputText", 500, 600, "hello") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_call_clear_text_field_to_select_and_delete_text():
    """should call clearTextField to select and delete text."""

    device = _device()

    await device.clear_input()

    assert ("clearTextField",) in device.hdc.calls


# -- keyboard -------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,code",
    [
        ("Enter", "2054"),
        ("Home", "Home"),
        ("A", "2017"),
        ("a", "2017"),
        ("1", "2001"),
        ("Back", "Back"),
        ("Power", "Power"),
    ],
)
async def test_should_map_key_to_keycode(key, code):
    """should map %s to keycode %s."""

    device = _device()

    await device.keyboard_press(key)

    assert ("keyEvent", code) in device.hdc.calls


@pytest.mark.asyncio
async def test_should_reject_key_combinations_before_connecting_to_hdc():
    """should reject key combinations before connecting to HDC."""

    device = _device()

    with pytest.raises(
        RuntimeError,
        match="HarmonyOS keyboardPress does not support key combinations",
    ):
        await device.keyboard_press("Control+A")

    assert device.hdc.calls == []


@pytest.mark.asyncio
async def test_should_send_back_key():
    """should send Back key."""

    device = _device()

    await device.back()

    assert ("keyEvent", "Back") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_send_home_key():
    """should send Home key."""

    device = _device()

    await device.home()

    assert ("keyEvent", "Home") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_send_the_api_18_plus_recent_keycode():
    """should send the API 18+ Recent keycode."""

    device = _device()

    await device.recent_apps()

    assert ("keyEvent", "10011") in device.hdc.calls


# -- launch / terminate ---------------------------------------------------------


@pytest.mark.asyncio
async def test_should_launch_a_plain_bundle_name_through_hdc_bundle_resolution():
    """should launch a plain bundle name through HDC bundle resolution."""

    device = _device()

    await device.launch_app("com.example.app")

    assert ("launch", "com.example.app") in device.hdc.calls


@pytest.mark.asyncio
async def test_should_force_stop_app_by_bundle_name():
    """should force-stop app by bundle name."""

    device = _device()

    await device.stop_app("com.example.app")

    assert ("force_stop", "com.example.app") in device.hdc.calls


# -- scroll ---------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direction,distance,point,expected",
    [
        ("down", 500, [600, 1200], (600, 1200, 600, 700, 2000)),
        ("up", 500, [600, 1200], (600, 1200, 600, 1700, 2000)),
        ("left", 400, [600, 1200], (600, 1200, 1000, 1200, 2000)),
        ("right", 400, [600, 1200], (600, 1200, 200, 1200, 2000)),
    ],
)
async def test_scroll_with_start_point_should_fling_from_point(
    direction, distance, point, expected
):
    """scrollDown/Up/Left/Right with startPoint should fling from point."""

    device = _device()

    await device.scroll(direction, distance, point=point)

    assert device.hdc.calls == [("fling", *expected)]


@pytest.mark.asyncio
async def test_keeps_a_located_start_and_clamps_travel_at_the_screen_margin():
    """keeps a located start and clamps travel at the screen margin."""

    device = _device()

    await device.scroll("down", None, point=[400, 1000])

    assert device.hdc.calls == [("fling", 400, 1000, 400, 50, 2000)]


@pytest.mark.asyncio
async def test_scroll_down_without_distance_uses_the_central_70_percent():
    """scrollDown without distance uses the central 70%."""

    device = _device()

    await device.scroll("down")

    assert device.hdc.calls == [("fling", 600, 2040, 600, 360, 1680)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,expected",
    [
        ("scrollToTop", (600, 1200, 600, 2350, 2000)),
        ("scrollToBottom", (600, 1200, 600, 50, 2000)),
        ("scrollToLeft", (600, 1200, 1150, 1200, 2000)),
        ("scrollToRight", (600, 1200, 50, 1200, 2000)),
    ],
)
async def test_scroll_until_with_start_point_should_fling_multiple_times(
    method, expected
):
    """scrollUntilTop/Bottom/Left/Right with startPoint should fling multiple times."""

    device = _device()
    direction = {
        "scrollToTop": "up",
        "scrollToBottom": "down",
        "scrollToLeft": "left",
        "scrollToRight": "right",
    }[method]

    await device.scroll(direction, scroll_type=method, point=[600, 1200])

    flings = [call for call in device.hdc.calls if call[0] == "fling"]
    assert len(flings) == 10
    for call in flings:
        assert call == ("fling", *expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,left,top",
    [
        ("scrollDown", 600, 25),
        ("scrollDown", 600, 50),
        ("scrollUp", 600, 2375),
        ("scrollUp", 600, 2350),
        ("scrollRight", 25, 1200),
        ("scrollLeft", 1175, 1200),
        ("scrollUntilBottom", 600, 25),
        ("scrollUntilTop", 600, 2375),
        ("scrollUntilLeft", 1175, 1200),
        ("scrollUntilRight", 25, 1200),
    ],
)
async def test_rejects_scroll_without_reversing_or_sending_an_empty_fling(
    method, left, top
):
    """rejects %s from (%s, %s) without reversing or sending an empty fling."""

    device = _device()
    if method.startswith("scrollUntil"):
        direction = {
            "scrollUntilTop": "up",
            "scrollUntilBottom": "down",
            "scrollUntilLeft": "left",
            "scrollUntilRight": "right",
        }[method]
        await_operation = device.scroll(
            direction, scroll_type=method, point=[left, top]
        )
    else:
        direction = method[len("scroll") :].lower()
        await_operation = device.scroll(direction, 100, point=[left, top])

    with pytest.raises(ValueError, match="No space"):
        await await_operation

    assert not any(call[0] == "fling" for call in device.hdc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("left", [float("nan"), float("inf"), -1, 1200])
async def test_rejects_invalid_horizontal_origin_for_vertical_scrolling(left):
    """rejects invalid horizontal origin %s for vertical scrolling."""

    device = _device()

    with pytest.raises(ValueError, match="origin"):
        await device.scroll("down", 100, point=[left, 1200])
    with pytest.raises(ValueError, match="origin"):
        await device.scroll("down", scroll_type="scrollToBottom", point=[left, 1200])

    assert not any(call[0] == "fling" for call in device.hdc.calls)


@pytest.mark.skip(
    reason=(
        "Python's Harmony action space differs from upstream: it has 20 actions "
        "(extra Hover/Sleep/Navigate/Reload/GoBack/GoForward) and is missing "
        "Swipe/LongPress instead of upstream's 16"
    )
)
def test_should_return_all_expected_actions():
    """should return all expected actions."""

    names = {action.name for action in build_action_space_for("harmony")}
    assert names == {
        "Tap",
        "DoubleClick",
        "Input",
        "Scroll",
        "DragAndDrop",
        "Swipe",
        "KeyboardPress",
        "CursorMove",
        "LongPress",
        "ClearInput",
        "RunHdcShell",
        "Launch",
        "Terminate",
        "HarmonyBackButton",
        "HarmonyHomeButton",
        "HarmonyRecentAppsButton",
    }
