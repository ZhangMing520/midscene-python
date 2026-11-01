"""HarmonyOS key name -> uitest keyEvent code mapping.

Synced from upstream packages/harmony/src/keycode.ts. Numeric values follow
the public OpenHarmony Input Kit KeyCode enum.
"""

from typing import List
NAMED_HARMONY_KEY_CODES = {
    "Enter": "2054",
    "Backspace": "2055",
    "Tab": "2049",
    "Escape": "2070",
    "Home": "Home",
    "ArrowUp": "2012",
    "ArrowDown": "2013",
    "ArrowLeft": "2014",
    "ArrowRight": "2015",
    "Space": "2050",
    "Delete": "2071",
    "Alt": "2045",
    "Shift": "2047",
    "Control": "2072",
    "Meta": "2076",
    "Back": "Back",
    "Power": "Power",
}

_KEY_NAME_ALIASES = {
    "return": "Enter",
    "esc": "Escape",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "ctrl": "Control",
}


def _unsupported_key(key_name: str) -> RuntimeError:
    return RuntimeError(
        f"Unsupported HarmonyOS keyboardPress key: {key_name!r}. Use "
        'typeText() for text input, or pass a supported key name such as '
        '"Enter", "A", or "1".'
    )


def _resolve_single_key(key_name: str) -> str:
    trimmed = key_name.strip()
    if not trimmed:
        raise _unsupported_key(key_name)

    alias = _KEY_NAME_ALIASES.get(trimmed.lower())
    normalized = alias or trimmed

    # digits name KEY_1.. (2001..2010); letters name KEY_A.. (2017..2042)
    import re

    if re.fullmatch(r"[0-9]", normalized):
        return str(2000 + int(normalized))
    if re.fullmatch(r"[a-z]", normalized, re.IGNORECASE):
        index = ord(normalized.upper()) - 65
        return str(2017 + index)

    named = NAMED_HARMONY_KEY_CODES.get(normalized) or NAMED_HARMONY_KEY_CODES.get(
        normalized.lower()
    )
    if named:
        return named
    raise _unsupported_key(key_name)


def resolve_harmony_key_codes(key_name: str) -> List[str]:
    """Resolve one logical key name to uitest keyEvent code(s).
    Key combinations are not supported (upstream)."""
    trimmed = key_name.strip()
    if "+" in trimmed:
        raise RuntimeError(
            f"HarmonyOS keyboardPress does not support key combinations: {key_name!r}"
        )
    return [_resolve_single_key(trimmed)]
