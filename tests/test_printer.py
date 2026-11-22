"""Synced from upstream packages/cli/tests/unit-test/printer.test.ts."""

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
