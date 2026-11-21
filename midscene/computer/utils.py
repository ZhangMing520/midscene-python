"""Computer helpers (upstream utils.ts)."""

import platform


def version() -> str:
    import midscene

    return midscene.__version__


def is_mac() -> bool:
    """True on macOS; the modifier key differs there (Cmd vs Ctrl/Win)."""
    return platform.system() == "Darwin"


__all__ = ["version", "is_mac"]
