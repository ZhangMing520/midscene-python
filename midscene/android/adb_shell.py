"""Shell-text escaping and Yadb routing (upstream adb-shell.ts)."""

import re

YADB_VERSION = "v1.1.1"
YADB_DEVICE_PATH = "/data/local/tmp/yadb"


def escape_for_shell(text: str) -> str:
    """Escape text for safe use inside single-quoted shell strings.

    In single quotes all characters are literal except ' itself; newlines are
    converted to literal \n (yadb interprets them back to real newlines).
    """
    return text.replace("'", "'\\''").replace("\n", "\\n")


def shell_escape_arg(text: str) -> str:
    """Escape a string as a single `adb shell input text` argument.

    Wraps the value in single quotes so the device shell does not interpret
    spaces, &, ;, |, $, ` etc. Internal single quotes use the '\'' sequence.
    """
    return "'" + text.replace("'", "'\\''") + "'"


def should_use_yadb_for_text(text: str) -> bool:
    """True when `adb shell input text` cannot reliably deliver this text:
    non-ASCII (Chinese etc.), format specifiers, shell-special characters, or
    mixed quotes (upstream shouldUseYadbForText)."""
    has_non_ascii = any(ord(ch) >= 0x80 for ch in text)
    has_format_specifiers = bool(re.search(r"%[a-zA-Z]", text))
    has_shell_special_chars = bool(re.search(r"[\\`$]", text))
    has_both_quotes = '"' in text and "'" in text
    return (
        has_non_ascii
        or has_format_specifiers
        or has_shell_special_chars
        or has_both_quotes
    )


__all__ = [
    "YADB_VERSION",
    "YADB_DEVICE_PATH",
    "escape_for_shell",
    "shell_escape_arg",
    "should_use_yadb_for_text",
]
