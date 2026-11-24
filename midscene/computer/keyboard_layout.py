"""en-US shifted characters (upstream computer/src/keyboard-layout.ts).

This is intentionally not a universal keyboard-layout map. Other layouts can
place these characters on different keys or modifier levels.
"""

US_SHIFTED_CHARACTER_KEYS: dict[str, str] = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}


def resolve_shifted_key(
    character: str, keyboard_layout: str | None = None
) -> str | None:
    """Resolve an uppercase letter or en-US shifted char to its base key."""
    if len(character) == 1 and "A" <= character <= "Z":
        return character.lower()

    if keyboard_layout == "en-US":
        return US_SHIFTED_CHARACTER_KEYS.get(character)
    return None


__all__ = ["US_SHIFTED_CHARACTER_KEYS", "resolve_shifted_key"]
