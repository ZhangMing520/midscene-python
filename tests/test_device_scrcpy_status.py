"""Port of upstream packages/android/tests/unit-test/device-scrcpy-status.test.ts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from midscene.android.device import AndroidDevice, AndroidDeviceConfig
from midscene.android.scrcpy_manager import ScrcpyStatus


def _device(scrcpy_config):
    return AndroidDevice(
        "device",
        AndroidDeviceConfig(device_id="device", scrcpy_config=scrcpy_config),
    )


def test_should_expose_scrcpy_status_from_the_device_adapter():
    """should expose scrcpy status from the device adapter."""

    device = _device({"enabled": True})
    status = ScrcpyStatus(
        enabled=True,
        connected=False,
        last_error="codec not ready",
        retry_after=1_000_000 + 5_000,
    )
    device._scrcpy_adapter = SimpleNamespace(get_status=lambda: status)

    assert device.get_scrcpy_status() is status


@pytest.mark.asyncio
async def test_should_retry_scrcpy_on_the_same_androiddevice_instance():
    """should retry scrcpy on the same AndroidDevice instance.

    Python's AndroidDevice.retry_scrcpy() reuses the lazily created adapter;
    unlike upstream it does not pass DevicePhysicalInfo (the Python adapter
    ignores that argument), and it checks ``is_configured()`` which is the same
    value exposed as ``getStatus().enabled``.
    """

    device = _device({"enabled": True})
    status = ScrcpyStatus(
        enabled=True, connected=True, last_error=None, retry_after=None
    )
    adapter = SimpleNamespace(
        is_configured=lambda: True,
        initialize=AsyncMock(return_value=None),
        get_status=lambda: status,
    )
    device._scrcpy_adapter = adapter

    assert await device.retry_scrcpy() is status
    adapter.initialize.assert_awaited_once()
    # The retry happened on the adapter already owned by this device instance.
    assert device._scrcpy_adapter is adapter


@pytest.mark.asyncio
async def test_should_reject_explicit_retries_when_scrcpy_is_disabled():
    """should reject explicit retries when scrcpy is disabled."""

    device = _device({"enabled": False})

    with pytest.raises(RuntimeError, match="scrcpy is disabled"):
        await device.retry_scrcpy()
