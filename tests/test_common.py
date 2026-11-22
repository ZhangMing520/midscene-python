"""Synced from upstream packages/shared/tests/unit-test/common.test.ts."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from midscene.shared.common import (
    get_midscene_run_base_dir,
    get_midscene_run_dir,
    get_midscene_run_sub_dir,
    resolve_midscene_run_dir,
    run_with_midscene_run_dir,
    set_midscene_run_dir,
)


@pytest.fixture(autouse=True)
def _restore_run_dir():
    yield
    set_midscene_run_dir(None)


def test_resolves_relative_environment_paths_from_the_supplied_project_root(
    monkeypatch,
):
    """resolves relative environment paths from the supplied project root"""
    project = os.path.join(tempfile.gettempdir(), "project")
    monkeypatch.setenv("MIDSCENE_RUN_DIR", "artifacts")
    assert resolve_midscene_run_dir(project) == str(
        Path(project).resolve() / "artifacts"
    )


@pytest.mark.asyncio
async def test_isolates_concurrent_and_nested_roots_and_restores_the_application_default_after_errors():
    """isolates concurrent and nested roots and restores the application default after errors"""
    application = os.path.join(tempfile.gettempdir(), "application")
    nested = os.path.join(tempfile.gettempdir(), "nested")
    set_midscene_run_dir(application)

    async def run(root: str) -> None:
        with run_with_midscene_run_dir(root):
            assert get_midscene_run_dir() == root
            await asyncio.sleep(0)
            assert get_midscene_run_dir() == root
            with run_with_midscene_run_dir(nested):
                assert get_midscene_run_dir() == nested
            assert get_midscene_run_dir() == root

    await asyncio.gather(
        run(os.path.join(tempfile.gettempdir(), "project-a")),
        run(os.path.join(tempfile.gettempdir(), "project-b")),
    )
    with pytest.raises(RuntimeError, match="test"):
        with run_with_midscene_run_dir("/failed"):
            raise RuntimeError("test")
    assert get_midscene_run_dir() == application


def test_reports_invalid_roots_and_filesystem_errors_instead_of_using_a_different_directory(
    monkeypatch, tmp_path
):
    """reports invalid roots and filesystem errors instead of using a different directory"""
    with pytest.raises(TypeError, match="non-empty path"):
        set_midscene_run_dir("  ")

    monkeypatch.setenv("MIDSCENE_RUN_DIR", "")
    with pytest.raises(TypeError, match="non-empty path"):
        get_midscene_run_dir()

    file = tmp_path / "file"
    file.write_text("keep this file")
    set_midscene_run_dir(str(file))
    with pytest.raises(FileExistsError):
        get_midscene_run_base_dir()


def test_uses_an_explicit_process_local_run_directory_before_the_environment():
    """uses an explicit process-local run directory before the environment"""
    set_midscene_run_dir("/tmp/midscene-studio")

    assert get_midscene_run_dir() == "/tmp/midscene-studio"


def test_uses_the_explicit_process_local_directory_for_output_artifacts(tmp_path):
    """uses the explicit process-local directory for output artifacts"""
    run_dir = str(tmp_path)
    set_midscene_run_dir(run_dir)

    assert get_midscene_run_sub_dir("output") == os.path.join(run_dir, "output")
