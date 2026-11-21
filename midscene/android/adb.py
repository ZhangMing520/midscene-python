"""ADB process helpers (upstream android/src/adb.ts).

The upstream module wraps appium-adb; the Python SDK shells out to the adb
binary directly, so this module owns the subprocess contract.
"""

import asyncio
import os
import subprocess
from typing import List, Optional

from loguru import logger


def resolve_adb_executable(android_adb_path: Optional[str] = None) -> str:
    """Resolve the adb executable (explicit path > env > PATH)."""
    return (
        android_adb_path
        or os.environ.get("MIDSCENE_ADB_PATH")
        or "adb"
    )


async def run_adb_command(
    args: List[str],
    capture_output: bool = False,
    timeout: float = 30,
    adb_path: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run one adb command, optionally capturing stdout/stderr."""
    executable = resolve_adb_executable(adb_path)
    try:
        if capture_output:
            result = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                result.communicate(), timeout=timeout
            )
            return subprocess.CompletedProcess(
                args=[executable] + args,
                returncode=result.returncode,
                stdout=stdout,
                stderr=stderr,
            )

        result = await asyncio.create_subprocess_exec(executable, *args)
        returncode = await asyncio.wait_for(result.wait(), timeout=timeout)
        return subprocess.CompletedProcess(
            args=[executable] + args,
            returncode=returncode,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"ADB command timeout: {args}")
    except Exception as error:  # noqa: BLE001 - mirror upstream logging
        logger.error(f"ADB command failed: {args}, error: {error}")
        raise


__all__ = ["resolve_adb_executable", "run_adb_command"]
