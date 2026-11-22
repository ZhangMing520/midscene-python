"""
Android integration module for Midscene Python
"""

from midscene.android.device import AndroidDevice
from midscene.android.agent import AndroidAgent
from midscene.android.scrcpy_device_adapter import (
    ResolvedScrcpyConfig,
    ScrcpyDeviceAdapter,
    format_scrcpy_fresh_frame_failure,
)
from midscene.android.scrcpy_manager import (
    RawKeyframe,
    ScrcpyConfig,
    ScrcpyFreshFrameUnavailableError,
    ScrcpyScreenshotManager,
    ScrcpyStatus,
    ensure_scrcpy_server,
    is_scrcpy_fresh_frame_unavailable_error,
    resolve_scrcpy_frame_rate,
)

__all__ = [
    "AndroidDevice",
    "AndroidAgent",
    "RawKeyframe",
    "ResolvedScrcpyConfig",
    "ScrcpyConfig",
    "ScrcpyDeviceAdapter",
    "ScrcpyFreshFrameUnavailableError",
    "ScrcpyScreenshotManager",
    "ScrcpyStatus",
    "ensure_scrcpy_server",
    "format_scrcpy_fresh_frame_failure",
    "is_scrcpy_fresh_frame_unavailable_error",
    "resolve_scrcpy_frame_rate",
]
