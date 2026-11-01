"""Desktop automation (upstream @midscene/computer)."""

from .desktop import DesktopDevice

try:
    from .agent import DesktopAgent

    __all__ = ["DesktopDevice", "DesktopAgent"]
except ImportError:  # pragma: no cover - agent requires core agent deps
    __all__ = ["DesktopDevice"]
