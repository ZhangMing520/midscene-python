"""Geometry helpers for finding the iOS keyboard dismiss control.

Synced from upstream packages/ios/src/keyboard-dismiss.ts. These are pure
rectangle predicates so they can be unit tested without a device.
"""

from typing import TypedDict

KEYBOARD_ACCESSORY_TOOLBAR_MIN_HEIGHT = 24
KEYBOARD_ACCESSORY_TOOLBAR_MAX_HEIGHT = 80
KEYBOARD_ACCESSORY_TOOLBAR_MIN_HORIZONTAL_OVERLAP = 0.8
KEYBOARD_ACCESSORY_TOOLBAR_MIN_RIGHT_BUTTON_CENTER_RATIO = 0.65
KEYBOARD_ACCESSORY_TOOLBAR_MAX_GAP = 48

KEYBOARD_NAMED_BUTTON_MAX_DISTANCE = 100


class KeyboardAccessoryButton(TypedDict):
    id: str
    rect: dict[str, float]


def _has_positive_size(rect: dict[str, float]) -> bool:
    return rect["width"] > 0 and rect["height"] > 0


def _center_of(rect: dict[str, float]) -> dict[str, float]:
    return {
        "x": rect["x"] + rect["width"] / 2,
        "y": rect["y"] + rect["height"] / 2,
    }


def is_named_dismiss_button_near_keyboard(
    button_rect: dict[str, float],
    keyboard_rect: dict[str, float],
) -> bool:
    if not _has_positive_size(button_rect) or not _has_positive_size(keyboard_rect):
        return False

    button_center = _center_of(button_rect)
    return (
        keyboard_rect["x"]
        <= button_center["x"]
        <= keyboard_rect["x"] + keyboard_rect["width"]
        and keyboard_rect["y"] - KEYBOARD_NAMED_BUTTON_MAX_DISTANCE
        <= button_center["y"]
        <= keyboard_rect["y"] + keyboard_rect["height"]
    )


def keyboard_accessory_toolbar_gap(
    toolbar_rect: dict[str, float],
    keyboard_rect: dict[str, float],
) -> float:
    return keyboard_rect["y"] - (toolbar_rect["y"] + toolbar_rect["height"])


def is_keyboard_accessory_toolbar(
    toolbar_rect: dict[str, float],
    keyboard_rect: dict[str, float],
) -> bool:
    if not _has_positive_size(toolbar_rect) or not _has_positive_size(keyboard_rect):
        return False

    overlap_width = max(
        0,
        min(
            toolbar_rect["x"] + toolbar_rect["width"],
            keyboard_rect["x"] + keyboard_rect["width"],
        )
        - max(toolbar_rect["x"], keyboard_rect["x"]),
    )
    horizontal_overlap = overlap_width / keyboard_rect["width"]
    gap = keyboard_accessory_toolbar_gap(toolbar_rect, keyboard_rect)
    max_gap = max(KEYBOARD_ACCESSORY_TOOLBAR_MAX_GAP, toolbar_rect["height"])

    return (
        KEYBOARD_ACCESSORY_TOOLBAR_MIN_HEIGHT
        <= toolbar_rect["height"]
        <= KEYBOARD_ACCESSORY_TOOLBAR_MAX_HEIGHT
        and horizontal_overlap >= KEYBOARD_ACCESSORY_TOOLBAR_MIN_HORIZONTAL_OVERLAP
        and toolbar_rect["y"] <= keyboard_rect["y"]
        and gap >= -toolbar_rect["height"]
        and gap <= max_gap
    )


def select_keyboard_accessory_dismiss_button(
    toolbar_rect: dict[str, float],
    buttons: list[KeyboardAccessoryButton],
) -> KeyboardAccessoryButton | None:
    """Pick the single right-edge control of a standard accessory toolbar.

    Conservative on purpose: navigation controls on the left plus exactly one
    control aligned to the right edge.
    """
    if not _has_positive_size(toolbar_rect):
        return None

    right_region_start = (
        toolbar_rect["x"]
        + toolbar_rect["width"]
        * KEYBOARD_ACCESSORY_TOOLBAR_MIN_RIGHT_BUTTON_CENTER_RATIO
    )
    buttons_inside_toolbar = [
        button
        for button in buttons
        if _has_positive_size(button["rect"])
        and toolbar_rect["x"]
        <= _center_of(button["rect"])["x"]
        <= toolbar_rect["x"] + toolbar_rect["width"]
        and toolbar_rect["y"]
        <= _center_of(button["rect"])["y"]
        <= toolbar_rect["y"] + toolbar_rect["height"]
    ]
    left_side_buttons = [
        button
        for button in buttons_inside_toolbar
        if _center_of(button["rect"])["x"] < right_region_start
    ]
    right_side_buttons = [
        button
        for button in buttons_inside_toolbar
        if _center_of(button["rect"])["x"] >= right_region_start
    ]

    if not left_side_buttons or len(right_side_buttons) != 1:
        return None

    dismiss_button = right_side_buttons[0]
    right_edge_gap = (
        toolbar_rect["x"]
        + toolbar_rect["width"]
        - (dismiss_button["rect"]["x"] + dismiss_button["rect"]["width"])
    )
    max_right_edge_gap = max(toolbar_rect["height"], dismiss_button["rect"]["width"])
    if right_edge_gap < 0 or right_edge_gap > max_right_edge_gap:
        return None

    return dismiss_button


__all__ = [
    "KeyboardAccessoryButton",
    "is_keyboard_accessory_toolbar",
    "is_named_dismiss_button_near_keyboard",
    "keyboard_accessory_toolbar_gap",
    "select_keyboard_accessory_dismiss_button",
]
