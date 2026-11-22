"""Android device discovery and screen info helpers (upstream utils.ts)."""

import asyncio
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.android.adb import create_android_adb
from midscene.core.types import Size

DETAIL_LOOKUP_ADB_TIMEOUT_MS = 8000
DETAIL_LOOKUP_STEP_TIMEOUT_MS = 2000


def _get_device_option(
    device_options: Optional[Dict[str, Any]], *keys: str
) -> Any:
    for key in keys:
        if device_options and key in device_options:
            return device_options[key]
    return None


def _clean_prop(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_resolution(stdout: str) -> Optional[str]:
    override_size = re.search(r"Override size:\s*([^\r\n]+)", stdout)
    if override_size and override_size.group(1):
        return override_size.group(1).strip()
    physical_size = re.search(r"Physical size:\s*([^\r\n]+)", stdout)
    if physical_size and physical_size.group(1):
        return physical_size.group(1).strip()
    return None



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


async def get_connected_devices(
    device_options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """List connected Android devices (upstream getConnectedDevices)."""
    adb_executable: Optional[str] = None
    try:
        adb = await create_android_adb(
            adb_exec_timeout=60000,
            device_options=device_options,
        )
        adb_executable = adb.executable.path
        devices = await adb.get_connected_devices()
        logger.debug(f"Found {len(devices)} connected devices: {devices}")
        return devices
    except Exception as error:  # noqa: BLE001 - mirror upstream error wrapping
        logger.error(f"Failed to get device list: {error}")
        executable_context = (
            f" (ADB executable: {adb_executable})"
            if adb_executable
            else ""
        )
        raise RuntimeError(
            "Unable to get connected Android device list"
            f"{executable_context}, please check "
            "https://www.midscenejs.com/platforms/android#faq : "
            f"{error}"
        ) from error


async def _timed_detail_lookup(coro, label: str) -> Any:
    try:
        return await asyncio.wait_for(
            coro, timeout=DETAIL_LOOKUP_STEP_TIMEOUT_MS / 1000.0
        )
    except asyncio.TimeoutError as error:
        raise RuntimeError(
            f"{label} timed out after {DETAIL_LOOKUP_STEP_TIMEOUT_MS}ms"
        ) from error


async def get_connected_devices_with_details(
    device_options: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Enrich the connected-device list with model/brand/resolution/density."""
    devices = await get_connected_devices(device_options)
    if not devices:
        return []

    async def enrich(device: Dict[str, str]) -> Dict[str, Any]:
        detailed_device: Dict[str, Any] = dict(device)
        udid = device.get("udid")
        try:
            adb = await create_android_adb(
                adb_exec_timeout=DETAIL_LOOKUP_ADB_TIMEOUT_MS,
                device_options=device_options,
            )
            adb.set_device_id(udid)

            model_result, brand_result, size_result, density_result = (
                await asyncio.gather(
                    _timed_detail_lookup(
                        adb.shell(["getprop", "ro.product.model"]),
                        f"Android model lookup for {udid}",
                    ),
                    _timed_detail_lookup(
                        adb.shell(["getprop", "ro.product.brand"]),
                        f"Android brand lookup for {udid}",
                    ),
                    _timed_detail_lookup(
                        adb.shell(["wm", "size"]),
                        f"Android resolution lookup for {udid}",
                    ),
                    _timed_detail_lookup(
                        adb.get_screen_density(),
                        f"Android density lookup for {udid}",
                    ),
                    return_exceptions=True,
                )
            )

            if not isinstance(model_result, BaseException):
                detailed_device["model"] = _clean_prop(model_result)
            if not isinstance(brand_result, BaseException):
                detailed_device["brand"] = _clean_prop(brand_result)
            if not isinstance(size_result, BaseException):
                detailed_device["resolution"] = _parse_resolution(
                    str(size_result)
                )
            if not isinstance(density_result, BaseException) and isinstance(
                density_result, int
            ):
                detailed_device["density"] = density_result
        except Exception as error:  # noqa: BLE001 - keep the basic entry
            logger.debug(f"Failed to enrich Android device {udid}: {error}")

        return detailed_device

    return list(await asyncio.gather(*(enrich(device) for device in devices)))


__all__ = [
    "DETAIL_LOOKUP_ADB_TIMEOUT_MS",
    "DETAIL_LOOKUP_STEP_TIMEOUT_MS",
    "get_connected_devices",
    "get_connected_devices_with_details",
    "parse_adb_devices_output",
    "parse_screen_size_output",
    "parse_screen_density",
]
