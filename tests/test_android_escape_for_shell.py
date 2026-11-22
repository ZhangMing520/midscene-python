"""Synced from upstream
``packages/android/tests/unit-test/escape-for-shell.test.ts``."""


class TestEscapeForShell:
    def test_should_escape_single_quotes(self):
        from midscene.android.device import escape_for_shell

        assert escape_for_shell("it's") == "it'\\''s"

    def test_should_escape_newlines(self):
        from midscene.android.device import escape_for_shell

        assert escape_for_shell("a\nb") == "a\\nb"
