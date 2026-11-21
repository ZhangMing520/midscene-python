"""Android device discovery and screen info helpers (upstream utils.ts)."""

import re
from typing import List, Optional

from midscene.core.types import Size


def parse_adb_devices_output(output: str) -> List[str]:
    """Extract device serials from `adb devices` output."""
    devices: List[str] = []
    for line in output.strip().split("\n")[1:]:  # Skip header
        if "\t" in line:
            device_id = line.split("\t")[0]
            if device_id:
                devices.append(device_id)
    return devices


def parse_screen_size_output(output: str) -> Optional[Size]:
    """Parse `wm size` output, preferring the physical size."""
    for line in output.strip().splitlines():
        if "Physical size:" in line and "x" in line:
            size_str = line.split(":")[-1].strip()
            width, height = map(int, size_str.split("x"))
            return Size(width=width, height=height)
    if ":" in output:
        size_str = output.split(":")[-1].strip()
        if "x" in size_str:
            width, height = map(int, size_str.split("x"))
            return Size(width=width, height=height)
    return None


def parse_screen_density(output: str) -> int:
    """Parse `wm density`, preferring the override, default 160."""
    override = re.search(r"Override density:\s*(\d+)", output)
    if override:
        return int(override.group(1))
    physical = re.search(r"Physical density:\s*(\d+)", output)
    if physical:
        return int(physical.group(1))
    return 160


__all__ = [
    "parse_adb_devices_output",
    "parse_screen_size_output",
    "parse_screen_density",
]
