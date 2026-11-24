"""Port of upstream packages/harmony/tests/unit-test/keycode.test.ts.

Python's ``resolve_harmony_key_codes`` is a close port of the upstream helper.
Two representation differences are adapted here: error messages quote the key
with ``repr`` instead of ``JSON.stringify``, and a bare ``"+"`` is classified
as a key-combination attempt before the unknown-key branch.
"""

import pytest

from midscene.harmony.keycode import resolve_harmony_key_codes

NAMED_KEYS = [
    ("Enter", ["2054"]),
    ("Backspace", ["2055"]),
    ("Tab", ["2049"]),
    ("Escape", ["2070"]),
    ("Home", ["Home"]),
    ("ArrowUp", ["2012"]),
    ("ArrowDown", ["2013"]),
    ("ArrowLeft", ["2014"]),
    ("ArrowRight", ["2015"]),
    ("Space", ["2050"]),
    ("Delete", ["2071"]),
    ("Control", ["2072"]),
    ("Shift", ["2047"]),
    ("Alt", ["2045"]),
    ("Meta", ["2076"]),
    ("Back", ["Back"]),
    ("Power", ["Power"]),
]

ALIASES = [
    ("enter", ["2054"]),
    ("esc", ["2070"]),
    ("up", ["2012"]),
    ("down", ["2013"]),
    ("left", ["2014"]),
    ("right", ["2015"]),
    ("ctrl", ["2072"]),
]

UNKNOWN_KEYS = [
    "?",
    "/",
    "KeyA",
    "Digit1",
    "F5",
    "Numpad1",
    "CapsLock",
    "AudioVolumeMute",
    "2210",
    "Mute",
    "not-a-key",
    "中文",
]

COMBINATIONS = [
    "Control+A",
    "Ctrl+a",
    "Shift+1",
    "Control+Shift+A",
    "Control + Alt + Delete",
    "Control+",
    "Control++",
    "Shift+Slash",
]


@pytest.mark.parametrize("key_name,expected", NAMED_KEYS)
def test_maps_key_name_to_codes(key_name, expected):
    """maps %s to %j."""

    assert resolve_harmony_key_codes(key_name) == expected


@pytest.mark.parametrize(
    "digit,expected", [(str(digit), [str(2000 + digit)]) for digit in range(10)]
)
def test_maps_digit_key_to_codes(digit, expected):
    """maps digit key %s to %j."""

    assert resolve_harmony_key_codes(digit) == expected


@pytest.mark.parametrize(
    "letter,expected",
    [(chr(65 + index), [str(2017 + index)]) for index in range(26)],
)
def test_maps_letter_key_to_codes(letter, expected):
    """maps letter key %s to %j."""

    assert resolve_harmony_key_codes(letter) == expected


def test_treats_letter_key_names_case_insensitively():
    """treats letter key names case-insensitively."""

    assert resolve_harmony_key_codes("a") == ["2017"]


@pytest.mark.parametrize("key_name,expected", ALIASES)
def test_normalizes_alias_to_codes(key_name, expected):
    """normalizes alias %s to %j."""

    assert resolve_harmony_key_codes(key_name) == expected


@pytest.mark.parametrize("key_name", UNKNOWN_KEYS)
def test_rejects_unknown_key(key_name):
    """rejects unknown key %s."""

    with pytest.raises(RuntimeError, match="Unsupported HarmonyOS keyboardPress key"):
        resolve_harmony_key_codes(key_name)


@pytest.mark.parametrize("key_name", COMBINATIONS)
def test_rejects_key_combination(key_name):
    """rejects key combination %s."""

    with pytest.raises(
        RuntimeError,
        match="HarmonyOS keyboardPress does not support key combinations",
    ):
        resolve_harmony_key_codes(key_name)
