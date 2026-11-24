"""RunAdbShell planning/stdout helpers (upstream android adb-shell.ts)."""

import pytest

from midscene.android.adb_shell import (
    build_run_adb_shell_planning_feedback,
    get_adb_shell_stdout_or_throw,
    run_adb_shell_stdout_or_throw,
)


def test_build_run_adb_shell_planning_feedback_includes_command_and_stdout():
    """buildRunAdbShellPlanningFeedback returns command + stdout."""
    assert (
        build_run_adb_shell_planning_feedback(
            command="wm size", stdout="Physical size: 1080x2400"
        )
        == "Command: wm size\nStdout:\nPhysical size: 1080x2400"
    )


def test_build_run_adb_shell_planning_feedback_returns_none_for_empty_stdout():
    """buildRunAdbShellPlanningFeedback returns undefined for empty stdout."""
    assert build_run_adb_shell_planning_feedback(command="wm size", stdout="") is None


def test_get_adb_shell_stdout_or_throw_returns_plain_string_output():
    """getAdbShellStdoutOrThrow accepts a raw string result."""
    assert get_adb_shell_stdout_or_throw("cmd", "result") == "result"


def test_get_adb_shell_stdout_or_throw_returns_stdout_from_full_output():
    """getAdbShellStdoutOrThrow reads stdout from a full output object."""
    assert (
        get_adb_shell_stdout_or_throw("cmd", {"stdout": "result", "stderr": ""})
        == "result"
    )


def test_get_adb_shell_stdout_or_throw_rejects_stderr_output():
    """getAdbShellStdoutOrThrow throws when stderr is present."""
    with pytest.raises(RuntimeError) as error:
        get_adb_shell_stdout_or_throw(
            "cmd test",
            {"stdout": "", "stderr": "No shell command implementation."},
        )

    assert (
        "RunAdbShell command returned stderr.\n"
        "Command: cmd test\n"
        "Stderr:\n"
        "No shell command implementation.\n"
        "Stdout:\n"
        "<empty>"
    ) in str(error.value)


def test_get_adb_shell_stdout_or_throw_truncates_long_streams():
    """getAdbShellStdoutOrThrow truncates stdout/stderr in error messages."""
    with pytest.raises(RuntimeError) as error:
        get_adb_shell_stdout_or_throw(
            "cmd test",
            {"stdout": "o" * 240, "stderr": "e" * 240},
        )

    assert (
        "Stderr:\n"
        f"{'e' * 200}\n...[stderr truncated, 40 more characters]\n"
        "Stdout:\n"
        f"{'o' * 200}\n...[stdout truncated, 40 more characters]"
    ) in str(error.value)


class _FakeAdb:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def shell(self, command, options=None):
        self.calls.append((command, options))
        return self.result


@pytest.mark.asyncio
async def test_run_adb_shell_stdout_or_throw_passes_timeout_and_full_output_format():
    """runAdbShellStdoutOrThrow forwards options with the full output format."""
    adb = _FakeAdb({"stdout": "adb-result", "stderr": ""})

    result = await run_adb_shell_stdout_or_throw(adb, "sleep 2", {"timeout": 2000})

    assert result == "adb-result"
    assert adb.calls == [("sleep 2", {"timeout": 2000, "outputFormat": "full"})]
