"""Chrome binary discovery (upstream agent-tools/chrome-path.ts)."""

import os
import sys
from typing import List, Optional

from midscene.shared.logger import get_logger

MIDSCENE_CHROME_PATH = "MIDSCENE_CHROME_PATH"
MIDSCENE_MCP_CHROME_PATH = "MIDSCENE_MCP_CHROME_PATH"

_logger = get_logger("agent-tools:chrome-path")
_has_warned_legacy_chrome_path = False
_cached_system_chrome_path: Optional[str] = None


def get_system_chrome_path() -> Optional[str]:
    global _cached_system_chrome_path
    if _cached_system_chrome_path is not None:
        return _cached_system_chrome_path

    platform = sys.platform
    chrome_paths = {
        "darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "win32": [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            (
                f"C:\\Users\\{os.environ.get('USERNAME') or os.environ.get('USER')}"
                "\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"
            ),
        ],
    }
    if platform.startswith("linux"):
        paths: List[str] = [
            "/opt/google/chrome/chrome",
            "/opt/google/chrome/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    else:
        paths = chrome_paths.get(platform, [])

    found = next((path for path in paths if os.path.exists(path)), None)
    if found:
        _cached_system_chrome_path = found
    return found


def resolve_chrome_path() -> str:
    global _has_warned_legacy_chrome_path

    primary_env_path = os.environ.get(MIDSCENE_CHROME_PATH)
    legacy_env_path = os.environ.get(MIDSCENE_MCP_CHROME_PATH)
    env_path = primary_env_path or legacy_env_path
    if (
        not primary_env_path
        and legacy_env_path
        and not _has_warned_legacy_chrome_path
    ):
        _logger.warning(
            "MIDSCENE_MCP_CHROME_PATH is deprecated. "
            "Use MIDSCENE_CHROME_PATH instead."
        )
        _has_warned_legacy_chrome_path = True
    if env_path and env_path != "auto" and os.path.exists(env_path):
        return env_path
    system_path = get_system_chrome_path()
    if system_path:
        return system_path

    raise RuntimeError(
        "Chrome not found. Install Google Chrome or set MIDSCENE_CHROME_PATH "
        "environment variable."
    )


__all__ = [
    "MIDSCENE_CHROME_PATH",
    "MIDSCENE_MCP_CHROME_PATH",
    "get_system_chrome_path",
    "resolve_chrome_path",
]
