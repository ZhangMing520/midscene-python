"""Persistent CDP target store (upstream web-integration/cdp-target-store.ts).

Each CLI command is a fresh process, so the tab selected by a previous command
is persisted as a target id in the temp directory.  The next command reads it
back to bind to the exact same tab.
"""

import os
import tempfile
from typing import Optional

from midscene.shared.logger import get_logger

debug = get_logger("agent-tools:cdp:target-store")

TARGET_ID_FILE = os.path.join(tempfile.gettempdir(), "midscene-cdp-target-id")


def read_saved_target_id() -> Optional[str]:
    """Read the saved target id, or return None when no command stored one."""
    try:
        with open(TARGET_ID_FILE, encoding="utf-8") as handle:
            target_id = handle.read().strip()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeError(
            f"Failed to read CDP target ID from {TARGET_ID_FILE}"
        ) from error
    if not target_id:
        raise RuntimeError(f"CDP target ID file {TARGET_ID_FILE} is empty")
    return target_id


def save_target_id(target_id: str) -> None:
    """Save a target id so the next CLI command can rebind to the same tab."""
    try:
        with open(TARGET_ID_FILE, "w", encoding="utf-8") as handle:
            handle.write(target_id)
        debug.info("Saved targetId: %s", target_id)
    except OSError as error:
        raise RuntimeError(
            f"Failed to save CDP target ID to {TARGET_ID_FILE}"
        ) from error


def cleanup_target_id_file() -> None:
    """Discard the saved target id after disconnect or a browser swap."""
    try:
        if os.path.exists(TARGET_ID_FILE):
            os.unlink(TARGET_ID_FILE)
    except OSError:
        pass


__all__ = [
    "TARGET_ID_FILE",
    "cleanup_target_id_file",
    "read_saved_target_id",
    "save_target_id",
]
