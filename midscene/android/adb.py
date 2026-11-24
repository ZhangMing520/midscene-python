"""ADB process helpers (upstream android/src/adb.ts).

The upstream module wraps appium-adb; the Python SDK shells out to the adb
binary directly, so this module owns the subprocess contract.
"""

import asyncio
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from midscene.android.adb_shell import escape_for_shell
from midscene.shared.env.constants import (
    MIDSCENE_ADB_PATH,
    MIDSCENE_ADB_REMOTE_HOST,
    MIDSCENE_ADB_REMOTE_PORT,
)
from midscene.shared.env.global_config_manager import get_global_config_manager

DEFAULT_ADB_EXEC_TIMEOUT_MS = 60000


def resolve_adb_executable(android_adb_path: str | None = None) -> str:
    """Resolve the adb executable (explicit path > env > PATH)."""
    return android_adb_path or os.environ.get("MIDSCENE_ADB_PATH") or "adb"


async def run_adb_command(
    args: list[str],
    capture_output: bool = False,
    timeout: float = 30,
    adb_path: str | None = None,
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
    except TimeoutError as error:
        raise TimeoutError(f"ADB command timeout: {args}") from error
    except Exception as error:  # noqa: BLE001 - mirror upstream logging
        logger.error(f"ADB command failed: {args}, error: {error}")
        raise


@dataclass
class AdbExecutable:
    """Executable description exposed as ``adb.executable`` (upstream)."""

    path: str
    default_args: list[str] = field(default_factory=list)


def _decode_output(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="ignore")


def _parse_devices_with_state(output: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    lines = output.strip().splitlines()
    for line in lines[1:]:  # skip the "List of devices attached" header
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("*"):
            continue
        parts = re.split(r"\s+", trimmed)
        if not parts:
            continue
        devices.append(
            {
                "udid": parts[0],
                "state": parts[1] if len(parts) > 1 else "device",
            }
        )
    return devices


class AndroidAdb:
    """Minimal appium-adb compatible client backed by the adb binary.

    Exposes the subset the Python SDK consumes: device discovery, ``shell`` and
    screen density lookup, plus the ``executable``/``udid`` attributes upstream
    callers read.
    """

    def __init__(
        self,
        udid: str | None = None,
        adb_exec_timeout: float = DEFAULT_ADB_EXEC_TIMEOUT_MS,
        executable: str | None = None,
        remote_adb_host: str | None = None,
        remote_adb_port: int | None = None,
    ):
        self.udid = udid
        self.adb_exec_timeout = adb_exec_timeout
        self.executable = AdbExecutable(path=resolve_adb_executable(executable))
        self.remote_adb_host = remote_adb_host
        self.remote_adb_port = remote_adb_port

    def set_device_id(self, udid: str | None) -> None:
        """Select the serial used by subsequent commands (setDeviceId)."""
        self.udid = udid

    def _server_args(self) -> list[str]:
        args: list[str] = []
        if self.remote_adb_host:
            args.extend(["-H", self.remote_adb_host])
        if self.remote_adb_port is not None:
            args.extend(["-P", str(self.remote_adb_port)])
        return args

    def _device_args(self) -> list[str]:
        args = self._server_args()
        if self.udid:
            args.extend(["-s", self.udid])
        return args

    async def _run(
        self, args: list[str], timeout: float | None = None
    ) -> subprocess.CompletedProcess:
        return await run_adb_command(
            args,
            capture_output=True,
            timeout=(
                float(timeout)
                if timeout is not None
                else float(self.adb_exec_timeout) / 1000.0
            ),
            adb_path=self.executable.path,
        )

    async def get_connected_devices(self) -> list[dict[str, str]]:
        """Return connected devices as ``{udid, state}`` entries."""
        result = await self._run([*self._server_args(), "devices"])
        if result.returncode != 0:
            raise RuntimeError(_decode_output(result.stderr).strip())
        return _parse_devices_with_state(_decode_output(result.stdout))

    async def shell(
        self,
        args: Any,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run an adb shell command.

        ``options`` mirrors the Appium shell options (``timeout`` in
        milliseconds and ``outputFormat``). Without ``outputFormat`` the raw
        stdout string is returned; with ``outputFormat='full'`` a
        ``{'stdout', 'stderr'}`` mapping is returned.
        """
        options = dict(options or {})
        timeout_ms = kwargs.pop("timeout", options.get("timeout"))
        output_format = kwargs.pop("output_format", options.get("outputFormat"))

        if isinstance(args, (list, tuple)):
            command = " ".join(shlex.quote(str(value)) for value in args)
        else:
            command = str(args)

        result = await self._run(
            [*self._device_args(), "shell", command],
            timeout=(float(timeout_ms) / 1000.0 if timeout_ms is not None else None),
        )
        stdout = _decode_output(result.stdout)
        stderr = _decode_output(result.stderr)

        if output_format == "full":
            return {"stdout": stdout, "stderr": stderr}

        if result.returncode != 0:
            raise RuntimeError(
                stderr.strip() or f"adb shell exited with {result.returncode}"
            )
        return stdout

    async def get_screen_density(self) -> int:
        """Return the device density from ``wm density``."""
        output = await self.shell(["wm", "density"])
        override = re.search(r"Override density:\s*(\d+)", output)
        if override:
            return int(override.group(1))
        physical = re.search(r"Physical density:\s*(\d+)", output)
        if physical:
            return int(physical.group(1))
        raise RuntimeError("Unable to read Android screen density")


def _sdk_adb_path(sdk_root: str) -> str | None:
    candidate = Path(sdk_root) / "platform-tools" / "adb"
    return str(candidate) if candidate.exists() else None


async def create_android_adb(
    adb_exec_timeout: float,
    device_id: str | None = None,
    device_options: dict[str, Any] | None = None,
) -> AndroidAdb:
    """Create an adb client (upstream createAndroidAdb).

    Resolution order: explicit ``androidAdbPath``/``MIDSCENE_ADB_PATH``, then
    the Android SDK ``platform-tools/adb``, then ``adb`` from PATH. Remote
    ``-H``/``-P`` settings come from the device options or the
    ``MIDSCENE_ADB_REMOTE_*`` environment keys.
    """
    device_options = device_options or {}
    if not isinstance(device_options, dict):
        device_options = {}
    config_manager = get_global_config_manager()

    android_adb_path = (
        device_options.get("androidAdbPath")
        or device_options.get("android_adb_path")
        or config_manager.get_env_config_value(MIDSCENE_ADB_PATH)
    )
    remote_adb_host = (
        device_options.get("remoteAdbHost")
        or device_options.get("remote_adb_host")
        or config_manager.get_env_config_value(MIDSCENE_ADB_REMOTE_HOST)
    )
    remote_adb_port = (
        device_options.get("remoteAdbPort")
        or device_options.get("remote_adb_port")
        or config_manager.get_env_config_value(MIDSCENE_ADB_REMOTE_PORT)
    )
    resolved_port: int | None = None
    if remote_adb_port is not None:
        try:
            resolved_port = int(remote_adb_port)
        except (TypeError, ValueError):
            resolved_port = None

    if android_adb_path:
        return AndroidAdb(
            udid=device_id,
            adb_exec_timeout=adb_exec_timeout,
            executable=android_adb_path,
            remote_adb_host=remote_adb_host or None,
            remote_adb_port=resolved_port,
        )

    sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk_root:
        sdk_executable = _sdk_adb_path(sdk_root)
        if sdk_executable:
            return AndroidAdb(
                udid=device_id,
                adb_exec_timeout=adb_exec_timeout,
                executable=sdk_executable,
                remote_adb_host=remote_adb_host or None,
                remote_adb_port=resolved_port,
            )
        logger.warning(
            "Unable to initialize adb from Android SDK at "
            f'"{sdk_root}", falling back to adb from PATH: '
            "platform-tools/adb was not found"
        )

    return AndroidAdb(
        udid=device_id,
        adb_exec_timeout=adb_exec_timeout,
        executable=None,
        remote_adb_host=remote_adb_host or None,
        remote_adb_port=resolved_port,
    )


__all__ = [
    "AdbExecutable",
    "AndroidAdb",
    "DEFAULT_ADB_EXEC_TIMEOUT_MS",
    "create_android_adb",
    "escape_for_shell",
    "resolve_adb_executable",
    "run_adb_command",
]
