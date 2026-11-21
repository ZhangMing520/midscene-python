"""Shared helpers for web page interfaces (upstream web-integration/web-page.ts)."""

import sys
from typing import Any, Dict, List

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

_PRIMARY_MODIFIERS = ("Control", "Meta")

_EDIT_COMMANDS = {
    "a": "SelectAll",
    "c": "Copy",
    "v": "Paste",
}


def _canonical_key(token: str) -> str:
    lowered = token.lower()
    if lowered == "ctrl":
        return "Meta" if _IS_MAC else "Control"
    return _KEY_ALIASES.get(lowered, token)


def build_key_commands(key_name: str) -> List[Dict[str, Any]]:
    """Expand a keyName like 'Control+A' or 'Enter' into the key/command
    objects the Chrome extension expects (upstream normalizeKeyInputs +
    getKeyCommands)."""
    text = key_name.strip()
    whole_phrase = _KEY_ALIASES.get(text.lower())
    if whole_phrase is not None:
        keys = [whole_phrase]
    else:
        if len(text) > 1 and "+" in text:
            text = text.replace("+", " ")
        keys = [_canonical_key(token) for token in text.split()] or [key_name]
    has_primary = any(key in _PRIMARY_MODIFIERS for key in keys)
    commands = []
    for key in keys:
        command = _EDIT_COMMANDS.get(key.lower()) if has_primary else None
        commands.append({"key": key, "command": command} if command else {"key": key})
    return commands
