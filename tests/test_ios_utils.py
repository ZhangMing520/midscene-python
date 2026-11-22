"""Port of upstream ``packages/ios/tests/unit-test/utils.test.ts``."""

import pytest

from midscene.ios import utils as ios_utils
from midscene.ios.utils import check_ios_environment, check_mac_os_platform


class TestCheckMacOSPlatform:
    def test_should_return_true_for_macos_platform(self, monkeypatch):
        """should return true for macOS platform"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Darwin")

        result = check_mac_os_platform()

        assert result["isMacOS"] is True
        assert result["platform"] == "darwin"

    def test_should_return_false_for_windows_platform(self, monkeypatch):
        """should return false for Windows platform"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Windows")

        result = check_mac_os_platform()

        assert result["isMacOS"] is False
        assert result["platform"] == "win32"

    def test_should_return_false_for_linux_platform(self, monkeypatch):
        """should return false for Linux platform"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Linux")

        result = check_mac_os_platform()

        assert result["isMacOS"] is False
        assert result["platform"] == "linux"


class TestCheckIOSEnvironment:
    @pytest.mark.asyncio
    async def test_should_return_available_false_when_not_running_on_macos(
        self, monkeypatch
    ):
        """should return available false when not running on macOS"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Windows")

        result = await check_ios_environment()

        assert result["available"] is False
        assert "iOS development is only supported on macOS" in result["error"]
        assert "win32" in result["error"]

    @pytest.mark.asyncio
    async def test_should_return_available_false_when_running_on_linux(
        self, monkeypatch
    ):
        """should return available false when running on Linux"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Linux")

        result = await check_ios_environment()

        assert result["available"] is False
        assert "iOS development is only supported on macOS" in result["error"]
        assert "linux" in result["error"]

    @pytest.mark.asyncio
    async def test_should_return_available_true_when_all_tools_are_present(
        self, monkeypatch
    ):
        """should return available true when all tools are present"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Darwin")

        async def fake_run(command):
            return "/usr/bin/xcrun\n"

        async def fake_succeeds(command):
            return True

        monkeypatch.setattr(ios_utils, "_run_command", fake_run)
        monkeypatch.setattr(ios_utils, "_command_succeeds", fake_succeeds)

        result = await check_ios_environment()

        assert result["available"] is True
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_should_return_available_false_when_xcrun_is_missing(
        self, monkeypatch
    ):
        """should return available false when xcrun is missing"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Darwin")

        async def fake_run(command):
            return ""

        monkeypatch.setattr(ios_utils, "_run_command", fake_run)

        result = await check_ios_environment()

        assert result["available"] is False
        assert "xcrun not found" in result["error"]

    @pytest.mark.asyncio
    async def test_should_return_available_false_when_xcodebuild_is_missing(
        self, monkeypatch
    ):
        """should return available false when xcodebuild is missing"""
        monkeypatch.setattr(ios_utils.platform, "system", lambda: "Darwin")

        async def fake_run(command):
            return "/usr/bin/xcrun\n"

        async def fake_succeeds(command):
            return False

        monkeypatch.setattr(ios_utils, "_run_command", fake_run)
        monkeypatch.setattr(ios_utils, "_command_succeeds", fake_succeeds)

        result = await check_ios_environment()

        assert result["available"] is False
        assert "xcodebuild not found" in result["error"]
