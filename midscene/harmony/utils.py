"""HarmonyOS device discovery helpers (upstream utils.ts)."""

from typing import Dict, List, Optional

from loguru import logger

from midscene.harmony.hdc import HdcClient


async def get_connected_devices(
    hdc_path: Optional[str] = None,
    timeout: Optional[float] = None,
) -> List[Dict[str, str]]:
    """List connected HarmonyOS devices through HDC (upstream)."""
    hdc = HdcClient(
        hdc_path=hdc_path,
        timeout=timeout if timeout is not None else 60.0,
    )
    try:
        targets = await hdc.list_targets()
    except Exception as error:
        logger.error(f"Failed to get device list: {error}")
        raise RuntimeError(
            "Unable to get connected HarmonyOS device list, please ensure HDC "
            f"is properly configured: {error}"
        ) from error

    devices = [{"deviceId": device_id} for device_id in targets]
    logger.debug(f"Found {len(devices)} connected devices: {devices}")
    return devices


__all__ = ["get_connected_devices"]
