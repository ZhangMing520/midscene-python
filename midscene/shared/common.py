"""Run-directory helpers (upstream packages/shared/src/common.ts).

The Python SDK always runs in a node-like process, so the browser/worker
branches collapse to the filesystem behavior. Environment access is read
directly here to avoid importing the model configuration layer.
"""

import os
from pathlib import Path
from typing import Optional

DEFAULT_RUN_DIR_NAME = "midscene_run"

ERROR_CODE_NOT_IMPLEMENTED_AS_DESIGNED = "NOT_IMPLEMENTED_AS_DESIGNED"

_MIDSCENE_RUN_DIR = "MIDSCENE_RUN_DIR"

_configured_run_dir: Optional[str] = None


def _validate_run_dir(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("Midscene run directory must be a non-empty path.")
    return value


def set_midscene_run_dir(run_dir: Optional[str]) -> None:
    """Set the run directory for this process without touching env vars.

    Passing None restores the environment-based behavior.
    """
    global _configured_run_dir
    _configured_run_dir = (
        None if run_dir is None else _validate_run_dir(run_dir)
    )


def get_midscene_run_dir() -> str:
    """Return the configured run directory name (not resolved)."""
    return _validate_run_dir(
        _configured_run_dir
        or os.environ.get(_MIDSCENE_RUN_DIR)
        or DEFAULT_RUN_DIR_NAME
    )


def resolve_midscene_run_dir(base_dir: str) -> str:
    """Resolve the run directory against a caller-provided base directory."""
    return str(Path(base_dir).resolve() / _validate_run_dir(get_midscene_run_dir()))


def get_midscene_run_base_dir() -> str:
    """Resolve and create the run directory under the current work dir."""
    base_path = Path.cwd().resolve() / get_midscene_run_dir()
    base_path.mkdir(parents=True, exist_ok=True)
    return str(base_path)


def get_midscene_run_sub_dir(subdir: str) -> str:
    """Resolve and create a subdirectory inside the run directory."""
    target = Path(get_midscene_run_base_dir()) / subdir
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


__all__ = [
    "DEFAULT_RUN_DIR_NAME",
    "ERROR_CODE_NOT_IMPLEMENTED_AS_DESIGNED",
    "get_midscene_run_base_dir",
    "get_midscene_run_dir",
    "get_midscene_run_sub_dir",
    "resolve_midscene_run_dir",
    "set_midscene_run_dir",
]
