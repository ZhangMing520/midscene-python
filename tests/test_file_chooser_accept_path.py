"""Synced from upstream
``packages/core/tests/unit-test/file-chooser-accept-path.test.ts``."""

import pytest


def test_should_throw_for_non_existent_relative_path(tmp_path):
    from midscene.core.agent.file_chooser import _normalize_file_paths

    with pytest.raises(FileNotFoundError, match="File not found"):
        _normalize_file_paths(str(tmp_path / "missing.txt"))
