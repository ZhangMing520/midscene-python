"""Locate the per-platform rdp-helper binary (upstream helper-binary.ts)."""

import platform
from pathlib import Path
from typing import Optional

PLATFORM_BINARY_MAP = {
    "Darwin": ("darwin", "rdp-helper"),
    "Linux": ("linux", "rdp-helper"),
    "Windows": ("win32", "rdp-helper.exe"),
}


def get_rdp_helper_binary_path(package_root: Optional[str] = None) -> str:
    """Locate the rdp-helper binary shipped with the package."""
    system = platform.system()
    mapping = PLATFORM_BINARY_MAP.get(system)
    if not mapping:
        raise RuntimeError(
            f"@midscene/computer RDP helper does not support platform {system}"
        )
    directory, file_name = mapping
    root = Path(package_root) if package_root else Path(__file__).parent
    for candidate in (
        root / ".." / "bin" / directory / file_name,
        root / "bin" / directory / file_name,
    ):
        candidate = candidate.resolve()
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        f"rdp-helper binary not found for {system}; expected at "
        f"{(root / 'bin' / directory / file_name).resolve()}"
    )


__all__ = ["PLATFORM_BINARY_MAP", "get_rdp_helper_binary_path"]
