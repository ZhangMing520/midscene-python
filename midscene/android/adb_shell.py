"""Shell-text escaping and Yadb routing (upstream adb-shell.ts)."""

import re
from typing import Any, Dict, Optional

YADB_VERSION = "v1.1.1"
YADB_DEVICE_PATH = "/data/local/tmp/yadb"

EMPTY_ADB_SHELL_STDOUT = "<empty>"
MAX_RUN_ADB_SHELL_STDOUT = 200


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


def _normalize_shell_stream(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _truncate_adb_shell_stream(output: str, stream_name: str) -> str:
    if len(output) <= MAX_RUN_ADB_SHELL_STDOUT:
        return output
    remaining = len(output) - MAX_RUN_ADB_SHELL_STDOUT
    return (
        f"{output[:MAX_RUN_ADB_SHELL_STDOUT]}\n"
        f"...[{stream_name} truncated, {remaining} more characters]"
    )


def build_run_adb_shell_planning_feedback(
    command: Any = None,
    stdout: str = "",
) -> Optional[str]:
    """Build the planning feedback for a RunAdbShell result (upstream).

    Passes the full stdout through; context truncation belongs to the planning
    layer.
    """
    if stdout == "":
        return None

    command_text = (
        f"Command: {command}\n"
        if isinstance(command, str) and len(command) > 0
        else ""
    )
    return f"{command_text}Stdout:\n{stdout}"


def _build_adb_shell_stderr_error_message(
    command: str,
    stdout: str,
    stderr: str,
) -> str:
    return (
        "RunAdbShell command returned stderr.\n"
        f"Command: {command}\n"
        "Stderr:\n"
        f"{_truncate_adb_shell_stream(stderr, 'stderr')}\n"
        "Stdout:\n"
        f"{_truncate_adb_shell_stream(stdout, 'stdout') if stdout else EMPTY_ADB_SHELL_STDOUT}"
    )


def get_adb_shell_stdout_or_throw(
    command: str,
    output: Any,
) -> str:
    """Return stdout from an adb shell result, raising on recorded stderr."""
    if isinstance(output, str):
        return output

    if not isinstance(output, dict):
        return _normalize_shell_stream(output)

    stdout = _normalize_shell_stream(output.get("stdout"))
    stderr = _normalize_shell_stream(output.get("stderr"))

    if stderr:
        raise RuntimeError(
            _build_adb_shell_stderr_error_message(command, stdout, stderr)
        )

    return stdout


async def run_adb_shell_stdout_or_throw(
    adb: Any,
    command: str,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """Run `adb shell` and return stdout, raising when stderr is non-empty."""
    options = dict(options or {})
    request_options = {**options, "outputFormat": "full"}
    try:
        output = await adb.shell(command, request_options)
    except TypeError:
        # Plain Python adb wrappers accept the timeout as a keyword instead of
        # the Appium options object.
        keywords = dict(options)
        timeout_ms = keywords.pop("timeout", None)
        if timeout_ms is not None:
            keywords["timeout"] = float(timeout_ms) / 1000.0
        output = await adb.shell(command, **keywords)

    return get_adb_shell_stdout_or_throw(command, output)


__all__ = [
    "EMPTY_ADB_SHELL_STDOUT",
    "MAX_RUN_ADB_SHELL_STDOUT",
    "YADB_VERSION",
    "YADB_DEVICE_PATH",
    "build_run_adb_shell_planning_feedback",
    "escape_for_shell",
    "get_adb_shell_stdout_or_throw",
    "run_adb_shell_stdout_or_throw",
    "shell_escape_arg",
    "should_use_yadb_for_text",
]

