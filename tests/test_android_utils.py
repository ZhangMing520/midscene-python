"""Port of upstream ``packages/android/tests/unit-test/utils.test.ts``."""

import asyncio
from types import SimpleNamespace

import pytest

from midscene.android import utils as android_utils


class _FakeAdb:
    def __init__(self, devices=None, shell_results=None, density=None):
        self.executable = SimpleNamespace(path="/mock/platform-tools/adb")
        self.devices = devices or []
        self.shell_results = list(shell_results or [])
        self.density = density
        self.selected_device = None

    async def get_connected_devices(self):
        if isinstance(self.devices, Exception):
            raise self.devices
        return self.devices

    def set_device_id(self, device_id):
        if self.devices == "set-device-fails":
            raise RuntimeError("set device failed")
        self.selected_device = device_id

    async def shell(self, args, options=None):
        if self.shell_results:
            return self.shell_results.pop(0)
        return ""

    async def get_screen_density(self):
        return self.density


def _install_factory(monkeypatch, fakes):
    calls = []

    async def fake_create_android_adb(**kwargs):
        calls.append(kwargs)
        return fakes[len(calls) - 1]

    monkeypatch.setattr(
        android_utils, "create_android_adb", fake_create_android_adb
    )
    return calls


class TestGetConnectedDevices:
    @pytest.mark.asyncio
    async def test_should_return_a_list_of_connected_devices(self, monkeypatch):
        mock_devices = [{"udid": "device-1"}, {"udid": "device-2"}]
        calls = _install_factory(monkeypatch, [_FakeAdb(devices=mock_devices)])

        devices = await android_utils.get_connected_devices()

        assert calls[0] == {
            "adb_exec_timeout": 60000,
            "device_options": None,
        }
        assert devices == mock_devices

    @pytest.mark.asyncio
    async def test_should_use_the_provided_adb_options_for_device_discovery(
        self, monkeypatch
    ):
        device_options = {
            "androidAdbPath": "/custom/platform-tools/adb",
            "remoteAdbHost": "localhost",
            "remoteAdbPort": 5038,
        }
        calls = _install_factory(monkeypatch, [_FakeAdb(devices=[])])

        await android_utils.get_connected_devices(device_options)

        assert calls[0] == {
            "adb_exec_timeout": 60000,
            "device_options": device_options,
        }

    @pytest.mark.asyncio
    async def test_should_throw_a_formatted_error_if_getting_devices_fails(
        self, monkeypatch
    ):
        _install_factory(
            monkeypatch,
            [_FakeAdb(devices=RuntimeError("Failed to connect to ADB"))],
        )

        with pytest.raises(RuntimeError) as error:
            await android_utils.get_connected_devices()

        assert (
            "Unable to get connected Android device list "
            "(ADB executable: /mock/platform-tools/adb), please check "
            "https://www.midscenejs.com/platforms/android#faq : "
            "Failed to connect to ADB"
        ) in str(error.value)


class TestGetConnectedDevicesWithDetails:
    @pytest.mark.asyncio
    async def test_should_enrich_devices_with_model_resolution_and_density_when_available(
        self, monkeypatch
    ):
        discovery = _FakeAdb(
            devices=[{"udid": "device-1", "state": "device"}]
        )
        detail = _FakeAdb(
            shell_results=[
                "Pixel 8\n",
                "google\n",
                "Physical size: 1080x2400\n",
            ],
            density=420,
        )
        calls = _install_factory(monkeypatch, [discovery, detail])

        devices = await android_utils.get_connected_devices_with_details()

        assert detail.selected_device == "device-1"
        assert devices == [
            {
                "udid": "device-1",
                "state": "device",
                "model": "Pixel 8",
                "brand": "google",
                "resolution": "1080x2400",
                "density": 420,
            }
        ]
        assert calls[-1] == {
            "adb_exec_timeout": 8000,
            "device_options": None,
        }

    @pytest.mark.asyncio
    async def test_should_use_the_same_adb_options_for_discovery_and_detail_lookup(
        self, monkeypatch
    ):
        device_options = {
            "androidAdbPath": "/custom/platform-tools/adb",
            "remoteAdbHost": "localhost",
            "remoteAdbPort": 5038,
        }
        discovery = _FakeAdb(
            devices=[{"udid": "device-1", "state": "device"}]
        )
        detail = _FakeAdb(shell_results=["", "", ""], density=None)
        calls = _install_factory(monkeypatch, [discovery, detail])

        await android_utils.get_connected_devices_with_details(device_options)

        assert calls[0] == {
            "adb_exec_timeout": 60000,
            "device_options": device_options,
        }
        assert calls[1] == {
            "adb_exec_timeout": 8000,
            "device_options": device_options,
        }

    @pytest.mark.asyncio
    async def test_should_silently_fall_back_to_the_basic_device_list_when_detail_lookup_fails(
        self, monkeypatch
    ):
        mock_devices = [{"udid": "device-1", "state": "device"}]
        discovery = _FakeAdb(devices=mock_devices)
        detail = _FakeAdb(devices="set-device-fails")
        _install_factory(monkeypatch, [discovery, detail])

        devices = await android_utils.get_connected_devices_with_details()

        assert devices == mock_devices

    @pytest.mark.asyncio
    async def test_should_timeout_slow_detail_lookups_and_still_return_the_basic_device_entry(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            android_utils, "DETAIL_LOOKUP_STEP_TIMEOUT_MS", 10
        )
        mock_devices = [{"udid": "device-1", "state": "device"}]
        discovery = _FakeAdb(devices=mock_devices)

        class _SlowModelAdb(_FakeAdb):
            async def shell(self, args, options=None):
                if args == ["getprop", "ro.product.model"]:
                    await asyncio.sleep(5)
                if args == ["getprop", "ro.product.brand"]:
                    return "google\n"
                if args == ["wm", "size"]:
                    return "Physical size: 1080x2400\n"
                return ""

        detail = _SlowModelAdb(density=420)
        _install_factory(monkeypatch, [discovery, detail])

        devices = await android_utils.get_connected_devices_with_details()

        assert devices == [
            {
                "udid": "device-1",
                "state": "device",
                "brand": "google",
                "resolution": "1080x2400",
                "density": 420,
            }
        ]
