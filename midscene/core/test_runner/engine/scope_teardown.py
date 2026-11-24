"""Node scope teardown result parsing (upstream engine/scope-teardown.ts)."""

import os
from typing import Any


def report_paths_from_teardown(result: Any) -> list[str]:
    if result is None:
        return []
    if not isinstance(result, dict):
        raise TypeError("Node teardown result must be an object or undefined.")
    paths = result.get("reportPaths")
    if paths is None:
        return []
    if not isinstance(paths, (list, tuple)):
        raise TypeError("Node teardown reportPaths must be an array.")
    checked: list[str] = []
    for index, path in enumerate(paths):
        if not isinstance(path, str) or not path.strip():
            raise TypeError(
                f"Node teardown reportPaths[{index}] must be a non-empty string."
            )
        if not os.path.isabs(path):
            raise TypeError(
                f"Node teardown reportPaths[{index}] must be an absolute path."
            )
        checked.append(path)
    return checked


__all__ = ["report_paths_from_teardown"]
