"""Packaged resource path resolution (upstream android/src/resource-path.ts)."""

import os
import re
from typing import Callable

_ASAR_DIR_PATTERN = re.compile(r"\.asar([/\\])")


def resolve_external_resource_path(
    resource_path: str,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> str:
    """Resolve an asar-unpacked sibling for external processes when present.

    Electron can read files inside app.asar through Node APIs, but external
    processes cannot; hosts must configure asarUnpack and this resolves the
    unpacked sibling only when it exists.
    """
    unpacked_path = _ASAR_DIR_PATTERN.sub(r".asar.unpacked\1", resource_path)
    if unpacked_path != resource_path and path_exists(unpacked_path):
        return unpacked_path
    return resource_path


__all__ = ["resolve_external_resource_path"]
