"""Synced from upstream ``packages/ios/tests/unit-test/keyboard-dismiss.test.ts``."""

import pytest

from midscene.ios.keyboard_dismiss import (
    is_keyboard_accessory_toolbar,
    is_named_dismiss_button_near_keyboard,
    select_keyboard_accessory_dismiss_button,
)

KEYBOARD_RECT = {"x": 0, "y": 583, "width": 402, "height": 233}
TOOLBAR_RECT = {"x": 0, "y": 508, "width": 402, "height": 48}
LEFT_BUTTON = {
    "id": "previous",
    "rect": {"x": 21, "y": 513, "width": 41, "height": 38},
}
RIGHT_BUTTON = {
    "id": "dismiss",
    "rect": {"x": 341, "y": 513, "width": 40, "height": 38},
}


def test_recognizes_a_toolbar_adjacent_to_the_keyboard_in_portrait_and_landscape():
    """recognizes a toolbar adjacent to the keyboard in portrait and landscape"""
    assert is_keyboard_accessory_toolbar(TOOLBAR_RECT, KEYBOARD_RECT) is True
    assert (
        is_keyboard_accessory_toolbar(
            {"x": 0, "y": 254, "width": 844, "height": 48},
            {"x": 0, "y": 302, "width": 844, "height": 88},
        )
        is True
    )


@pytest.mark.parametrize(
    "description,candidate",
    [
        ("far above the keyboard", {**TOOLBAR_RECT, "y": 100}),
        ("too tall", {**TOOLBAR_RECT, "height": 120}),
        (
            "insufficiently overlapping",
            {**TOOLBAR_RECT, "x": 250, "width": 152},
        ),
        ("empty", {**TOOLBAR_RECT, "width": 0}),
    ],
    ids=[
        "far-above-the-keyboard",
        "too-tall",
        "insufficiently-overlapping",
        "empty",
    ],
)
def test_rejects_a_toolbar_that_is(description, candidate):
    """rejects a toolbar that is %s"""
    assert is_keyboard_accessory_toolbar(candidate, KEYBOARD_RECT) is False


def test_selects_one_right_edge_control_when_navigation_controls_exist_on_the_left():
    """selects one right-edge control when navigation controls exist on the left"""
    assert (
        select_keyboard_accessory_dismiss_button(
            TOOLBAR_RECT, [LEFT_BUTTON, RIGHT_BUTTON]
        )
        == RIGHT_BUTTON
    )


def test_rejects_a_custom_toolbar_with_only_a_right_side_business_action():
    """rejects a custom toolbar with only a right-side business action"""
    assert (
        select_keyboard_accessory_dismiss_button(TOOLBAR_RECT, [RIGHT_BUTTON])
        is None
    )


def test_rejects_an_ambiguous_toolbar_with_multiple_right_side_controls():
    """rejects an ambiguous toolbar with multiple right-side controls"""
    assert (
        select_keyboard_accessory_dismiss_button(
            TOOLBAR_RECT,
            [
                LEFT_BUTTON,
                {
                    "id": "save",
                    "rect": {"x": 275, "y": 513, "width": 45, "height": 38},
                },
                RIGHT_BUTTON,
            ],
        )
        is None
    )


def test_rejects_a_right_side_control_that_is_not_aligned_to_the_right_edge():
    """rejects a right-side control that is not aligned to the right edge"""
    assert (
        select_keyboard_accessory_dismiss_button(
            TOOLBAR_RECT,
            [
                LEFT_BUTTON,
                {
                    "id": "submit",
                    "rect": {"x": 265, "y": 513, "width": 40, "height": 38},
                },
            ],
        )
        is None
    )


def test_accepts_configured_controls_only_inside_the_keyboard_region():
    """accepts configured controls only inside the keyboard region"""
    assert (
        is_named_dismiss_button_near_keyboard(
            RIGHT_BUTTON["rect"], KEYBOARD_RECT
        )
        is True
    )
    assert (
        is_named_dismiss_button_near_keyboard(
            {"x": 320, "y": 200, "width": 60, "height": 40},
            KEYBOARD_RECT,
        )
        is False
    )
