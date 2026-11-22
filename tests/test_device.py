"""HarmonyOS device app-name mapping (upstream harmony device.test.ts)."""

import pytest

from midscene.harmony.device import HarmonyDevice


class _FakeHdc:
    def __init__(self):
        self.calls = []

    async def shell(self, command):
        self.calls.append(("shell", command))

    async def start_ability(self, bundle, ability):
        self.calls.append(("start_ability", bundle, ability))

    async def launch(self, bundle):
        self.calls.append(("launch", bundle))

    async def force_stop(self, bundle):
        self.calls.append(("force_stop", bundle))


def _device() -> HarmonyDevice:
    device = HarmonyDevice("test-device-id")
    device.hdc = _FakeHdc()

    async def get_hdc():
        return device.hdc

    device._get_hdc = get_hdc
    return device


class TestSetAppNameMapping:
    @pytest.mark.asyncio
    async def test_should_store_mapping_and_resolve_on_launch(self):
        device = _device()
        device.set_app_name_mapping({"browser": "com.huawei.hmos.browser"})

        await device.launch_app("Browser")

        assert ("launch", "com.huawei.hmos.browser") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_should_start_an_explicit_ability_from_app_name_mapping(self):
        device = _device()
        device.set_app_name_mapping({"Video App": "com.example.video/PhoneAbility"})

        await device.launch_app("video-app")

        assert (
            "start_ability",
            "com.example.video",
            "PhoneAbility",
        ) in device.hdc.calls
        assert not any(call[0] == "launch" for call in device.hdc.calls)

    @pytest.mark.asyncio
    async def test_should_fall_back_to_original_name_if_not_in_mapping(self):
        device = _device()
        device.set_app_name_mapping({})

        await device.launch_app("com.unknown.app")

        assert ("launch", "com.unknown.app") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_should_resolve_app_name_mapping_before_force_stop(self):
        device = _device()
        device.set_app_name_mapping({"music": "com.huawei.hmsapp.music"})

        await device.stop_app("Music")

        assert ("force_stop", "com.huawei.hmsapp.music") in device.hdc.calls

    @pytest.mark.asyncio
    async def test_should_use_only_the_bundle_part_of_a_mapped_bundle_ability_target(
        self,
    ):
        device = _device()
        device.set_app_name_mapping({"Video": "com.example.video/PhoneAbility"})

        await device.stop_app("Video")

        assert ("force_stop", "com.example.video") in device.hdc.calls
