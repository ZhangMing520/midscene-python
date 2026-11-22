"""Synced from upstream ``packages/android/tests/unit-test/adb.test.ts``.

Python ``create_android_adb()`` returns a lightweight ``AndroidAdb`` client
instead of an appium-adb ``ADB`` instance, but resolves the same inputs
(explicit executable, MIDSCENE_ADB_* env, Android SDK platform-tools).
"""

import pytest

from midscene.android.adb import create_android_adb


@pytest.mark.asyncio
async def test_uses_the_explicit_executable_and_remote_server_for_the_adb_client():
    """uses the explicit executable and remote server for the ADB client"""
    adb = await create_android_adb(
        adb_exec_timeout=8000,
        device_id="device-1",
        device_options={
            "androidAdbPath": "/custom/platform-tools/adb",
            "remoteAdbHost": "192.168.1.10",
            "remoteAdbPort": 5038,
        },
    )

    assert adb.udid == "device-1"
    assert adb.adb_exec_timeout == 8000
    assert adb.executable.path == "/custom/platform-tools/adb"
    assert adb.executable.default_args == []
    assert adb.remote_adb_host == "192.168.1.10"
    assert adb.remote_adb_port == 5038


@pytest.mark.asyncio
async def test_uses_midscene_adb_settings_when_device_options_are_absent(
    monkeypatch,
):
    """uses MIDSCENE_ADB settings when device options are absent"""
    monkeypatch.setenv("MIDSCENE_ADB_PATH", "/env/platform-tools/adb")
    monkeypatch.setenv("MIDSCENE_ADB_REMOTE_HOST", "adb.example.com")
    monkeypatch.setenv("MIDSCENE_ADB_REMOTE_PORT", "5040")

    adb = await create_android_adb(adb_exec_timeout=60000)

    assert adb.udid is None
    assert adb.executable.path == "/env/platform-tools/adb"
    assert adb.remote_adb_host == "adb.example.com"
    assert adb.remote_adb_port == 5040


@pytest.mark.asyncio
async def test_uses_appium_sdk_resolution_when_no_custom_executable_is_configured(
    monkeypatch, tmp_path
):
    """uses Appium SDK resolution when no custom executable is configured"""
    monkeypatch.delenv("MIDSCENE_ADB_PATH", raising=False)
    platform_tools = tmp_path / "platform-tools"
    platform_tools.mkdir()
    adb_binary = platform_tools / "adb"
    adb_binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)

    adb = await create_android_adb(
        adb_exec_timeout=60000,
        device_id="device-2",
    )

    assert adb.udid == "device-2"
    assert adb.executable.path == str(adb_binary)
    assert adb.remote_adb_host is None
    assert adb.remote_adb_port is None


@pytest.mark.asyncio
async def test_falls_back_to_path_when_the_configured_android_sdk_cannot_resolve_adb(
    monkeypatch, tmp_path
):
    """falls back to PATH when the configured Android SDK cannot resolve adb"""
    monkeypatch.delenv("MIDSCENE_ADB_PATH", raising=False)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "stale-sdk"))
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)

    adb = await create_android_adb(
        adb_exec_timeout=60000,
        device_id="device-3",
    )

    assert adb.executable.path == "adb"
    assert adb.udid == "device-3"


@pytest.mark.asyncio
async def test_preserves_the_path_fallback_when_no_android_sdk_root_is_configured(
    monkeypatch,
):
    """preserves the PATH fallback when no Android SDK root is configured"""
    monkeypatch.delenv("MIDSCENE_ADB_PATH", raising=False)
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)

    adb = await create_android_adb(
        adb_exec_timeout=60000,
        device_id="device-3",
    )

    assert adb.executable.path == "adb"
    assert adb.udid == "device-3"
