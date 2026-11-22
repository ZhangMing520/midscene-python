"""Synced from upstream packages/cli/tests/unit-test/printer.test.ts."""

import midscene.cli.printer as printer
from midscene.cli.printer import (
    context_info,
    context_task_list_summary,
    current_spinning_frame,
    format_yaml_progress_snapshot,
    single_task_info,
)
from midscene.cli.printer import resolve_is_tty


def test_returns_true_on_a_real_interactive_tty():
    """returns true on a real interactive TTY"""
    assert resolve_is_tty({}, True) is True


def test_returns_false_when_stdout_is_not_a_tty():
    """returns false when stdout is not a TTY"""
    assert resolve_is_tty({}, None) is False
    assert resolve_is_tty({}, False) is False


def test_falls_back_to_non_tty_for_the_explicit_opt_out_flag():
    """falls back to non-TTY for the explicit opt-out flag"""
    assert resolve_is_tty({"MIDSCENE_CLI_LOG_ON_NON_TTY": "1"}, True) is False


def test_honors_standard_non_interactive_signals_even_with_an_allocated_tty():
    """honors standard non-interactive signals even with an allocated TTY"""
    assert resolve_is_tty({"NO_COLOR": "1"}, True) is False
    assert resolve_is_tty({"TERM": "dumb"}, True) is False
    assert resolve_is_tty({"CI": "true"}, True) is False


def test_does_not_treat_term_xterm_as_non_interactive():
    """does not treat TERM=xterm as non-interactive"""
    assert resolve_is_tty({"TERM": "xterm-256color"}, True) is True


def test_spinner_constants_and_frame_selection():
    assert printer.indent == "  "
    assert printer.spinner_interval == 80
    assert printer.spinner_frames == ["◰", "◳", "◲", "◱"]
    assert current_spinning_frame() in printer.spinner_frames


def test_format_yaml_progress_snapshot_mentions_attempt_only_for_retries():
    assert format_yaml_progress_snapshot("running", 1, 1) == "running"
    assert (
        format_yaml_progress_snapshot("running", 2, 3)
        == "Attempt 2/3\nrunning"
    )


def test_context_info_renders_file_state_output_and_report(monkeypatch):
    monkeypatch.setattr(printer, "is_tty", False)
    info = context_info(
        {
            "file": "/tmp/project/cases/login.yaml",
            "player": {
                "status": "running",
                "currentTaskIndex": None,
                "output": "/tmp/project/output/login.json",
                "result": {"ok": True},
                "reportFile": "/tmp/project/report/login.html",
                "agentStatusTip": "thinking",
            },
        }
    )

    assert "cases/login.yaml" in info["fileNameToPrint"]
    assert "(navigating)" in info["contextActionText"]
    assert "output: /tmp/project/output/login.json" in info["outputText"]
    assert "report: /tmp/project/report/login.html" in info["reportText"]
    assert "cases/login.yaml" in info["mergedText"]
    assert "agent status: thinking" in info["mergedText"]


def test_single_task_info_reports_step_and_error(monkeypatch):
    monkeypatch.setattr(printer, "is_tty", False)
    running = single_task_info(
        {"name": "Open page", "status": "running", "currentStep": 1, "totalSteps": 4}
    )
    assert "Open page" in running["mergedLine"]
    assert "(task 2/4)" in running["stepText"]

    failed = single_task_info(
        {
            "name": "Submit",
            "status": "error",
            "error": {"message": "button not found"},
        }
    )
    assert "error:" in failed["errorText"]
    assert "button not found" in failed["errorText"]


def test_context_task_list_summary_groups_task_lines(monkeypatch):
    monkeypatch.setattr(printer, "is_tty", False)
    summary = context_task_list_summary(
        [
            {"name": "first", "status": "done"},
            {"name": "second", "status": "running", "currentStep": 0, "totalSteps": 2},
        ],
        {"file": "/tmp/project/a.yaml", "player": {"status": "running"}},
    )

    lines = summary.split("\n")
    assert "a.yaml" in lines[0]
    assert any("first" in line for line in lines)
    assert any("second" in line for line in lines)
