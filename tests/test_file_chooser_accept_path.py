"""Synced from upstream
``packages/core/tests/unit-test/file-chooser-accept-path.test.ts``."""

import os

import pytest

from midscene.core.agent.file_chooser import normalize_file_chooser_accept
from midscene.core.agent.utils import normalize_file_paths


class TestAcceptRelativePaths:
    def test_should_resolve_relative_path_with_dot_prefix(self, tmp_path, monkeypatch):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        monkeypatch.chdir(tmp_path)
        assert normalize_file_chooser_accept("./path-test-file.txt") == [str(target)]

    def test_should_resolve_bare_relative_path(self, tmp_path, monkeypatch):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        monkeypatch.chdir(tmp_path)
        assert normalize_file_chooser_accept("path-test-file.txt") == [str(target)]

    def test_should_resolve_relative_path_with_parent_segments(
        self, tmp_path, monkeypatch
    ):
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        target = fixtures / "path-test-file.txt"
        target.write_text("path test content")
        monkeypatch.chdir(tmp_path)
        assert normalize_file_chooser_accept(
            "fixtures/../fixtures/path-test-file.txt"
        ) == [str(target)]

    def test_should_keep_absolute_path_as_is(self, tmp_path):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        assert normalize_file_chooser_accept(str(target)) == [str(target)]

    def test_should_accept_string_input_and_normalize_to_array(self, tmp_path):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        result = normalize_file_chooser_accept(str(target))
        assert isinstance(result, list) and len(result) == 1

    def test_should_accept_array_input(self, tmp_path):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        assert normalize_file_chooser_accept([str(target)]) == [str(target)]

    def test_should_throw_for_non_existent_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError) as exc:
            normalize_file_chooser_accept("./non-existent-file.txt")
        message = str(exc.value)
        assert "File not found: ./non-existent-file.txt. Resolved to: " in message
        assert f"Current working directory: {os.getcwd()}" in message

    def test_should_throw_for_non_existent_absolute_path(self):
        with pytest.raises(FileNotFoundError, match="File not found"):
            normalize_file_chooser_accept("/absolute/non-existent-file.txt")

    def test_should_resolve_multiple_relative_paths(self, tmp_path, monkeypatch):
        target = tmp_path / "path-test-file.txt"
        target.write_text("path test content")
        monkeypatch.chdir(tmp_path)
        assert normalize_file_chooser_accept(["path-test-file.txt", str(target)]) == [
            str(target),
            str(target),
        ]


class TestNormalizeFilePaths:
    def test_throws_in_browser_environments(self):
        with pytest.raises(
            RuntimeError,
            match="File chooser is not supported in browser environment",
        ):
            normalize_file_paths(["file.txt"], {"isInBrowser": True})

    def test_resolves_relative_paths_and_validates_existence(self):
        result = normalize_file_paths(
            ["./upload.txt"],
            {
                "fileExists": lambda path: path == "/project/upload.txt",
                "resolvePath": lambda _path: "/project/upload.txt",
                "wslDistroName": "",
            },
        )
        assert result == ["/project/upload.txt"]

    def test_throws_with_original_and_resolved_paths_when_missing(self):
        with pytest.raises(FileNotFoundError) as exc:
            normalize_file_paths(
                ["./missing.txt"],
                {
                    "cwd": "/project",
                    "fileExists": lambda _path: False,
                    "resolvePath": lambda _path: "/project/missing.txt",
                },
            )
        assert (
            "File not found: ./missing.txt. Resolved to: /project/missing.txt. "
            "Current working directory: /project"
        ) in str(exc.value)

    def test_converts_wsl_mounted_windows_drive_paths(self):
        result = normalize_file_paths(
            ["/mnt/c/Users/me/upload.zip"],
            {
                "fileExists": lambda _path: True,
                "resolvePath": lambda path: path,
                "wslDistroName": "Ubuntu-22.04",
            },
        )
        assert result == ["C:\\Users\\me\\upload.zip"]

    def test_converts_wsl_distro_local_paths_to_unc_paths(self):
        result = normalize_file_paths(
            ["/home/me/upload.zip"],
            {
                "fileExists": lambda _path: True,
                "resolvePath": lambda path: path,
                "wslDistroName": "Ubuntu-22.04",
            },
        )
        assert result == ["\\\\wsl$\\Ubuntu-22.04\\home\\me\\upload.zip"]
