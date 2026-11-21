"""App-name mapping parity with upstream android/harmony appNameMapping."""

import pytest

from midscene.shared.utils import (
    merge_and_normalize_app_name_mapping,
    normalize_for_comparison,
)


class TestSharedAppNameMapping:
    def test_normalize_for_comparison(self):
        assert normalize_for_comparison("Google Play Store") == "googleplaystore"
        assert normalize_for_comparison("QQ 音乐") == "qq音乐"
        assert normalize_for_comparison("simple-app_name") == "simpleappname"

    def test_user_mapping_overrides_default(self):
        merged = merge_and_normalize_app_name_mapping(
            {"WeChat": "com.tencent.mm"},
            {"we chat": "com.custom.wechat"},
        )
        assert merged == {"wechat": "com.custom.wechat"}


class TestAndroidAppNameMapping:
    @pytest.mark.asyncio
    async def test_launch_resolves_friendly_name(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("dev")
        device.set_app_name_mapping(
            merge_and_normalize_app_name_mapping(
                {"WeChat": "com.tencent.mm", "Settings": "com.android.settings"}
            )
        )
        calls = []

        async def fake_run(args, **kwargs):
            calls.append(args)

        device._run_adb_command = fake_run
        await device.launch_app("we chat")
        await device.launch_app("Settings")
        await device.launch_app("com.example/.MainActivity")
        await device.launch_app("https://example.com")
        assert calls[0] == [
            "-s", "dev", "shell", "monkey",
            "-p", "com.tencent.mm", "-c", "android.intent.category.LAUNCHER", "1",
        ]
        assert calls[1] == [
            "-s", "dev", "shell", "monkey",
            "-p", "com.android.settings", "-c", "android.intent.category.LAUNCHER", "1",
        ]
        assert calls[2] == [
            "-s", "dev", "shell", "am", "start", "-n", "com.example/.MainActivity",
        ]
        assert calls[3] == [
            "-s", "dev", "shell", "am", "start",
            "-a", "android.intent.action.VIEW", "-d", "https://example.com",
        ]

    @pytest.mark.asyncio
    async def test_stop_resolves_friendly_name(self):
        from midscene.android.device import AndroidDevice

        device = AndroidDevice("dev")
        device.set_app_name_mapping({"微信": "com.tencent.mm"})
        calls = []

        async def fake_run(args, **kwargs):
            calls.append(args)

        device._run_adb_command = fake_run
        await device.stop_app("微信")
        await device.stop_app("com.example/.MainActivity")
        assert calls[0] == [
            "-s", "dev", "shell", "am", "force-stop", "com.tencent.mm",
        ]
        assert calls[1] == [
            "-s", "dev", "shell", "am", "force-stop", "com.example",
        ]


class TestHarmonyAppNameMapping:
    @pytest.mark.asyncio
    async def test_launch_and_stop_resolve_friendly_name(self):
        from midscene.harmony.device import HarmonyDevice

        device = HarmonyDevice("dev")
        device.set_app_name_mapping(
            {"设置": "com.huawei.hmos.settings", "相机": "com.huawei.hmos.camera"}
        )
        calls = []

        class FakeHdc:
            async def shell(self, command):
                calls.append(("shell", command))

            async def start_ability(self, bundle, ability):
                calls.append(("start_ability", bundle, ability))

            async def launch(self, bundle):
                calls.append(("launch", bundle))

            async def force_stop(self, bundle):
                calls.append(("force_stop", bundle))

        async def fake_get_hdc():
            return FakeHdc()

        device._get_hdc = fake_get_hdc
        await device.launch_app("设置")
        await device.launch_app("com.example/EntryAbility")
        await device.launch_app("https://example.com")
        await device.stop_app("相机")
        assert calls == [
            ("launch", "com.huawei.hmos.settings"),
            ("start_ability", "com.example", "EntryAbility"),
            ("shell", "aa start -U https://example.com"),
            ("force_stop", "com.huawei.hmos.camera"),
        ]
