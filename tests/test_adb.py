"""Synced from upstream ``packages/android/tests/unit-test/adb.test.ts``.

The Python SDK does not wrap appium-adb: ``android/adb.py`` only resolves an
adb executable string and runs the binary through ``run_adb_command()``, so the
upstream ``createAndroidAdb()`` client-construction cases are not portable.
"""

import pytest


@pytest.mark.skip(
    reason="Python android/adb.py has no createAndroidAdb()/appium-adb client; "
    "it resolves an executable and runs the adb binary via run_adb_command()"
)
def test_uses_the_explicit_executable_and_remote_server_for_the_adb_client():
    """uses the explicit executable and remote server for the ADB client"""
    pass


@pytest.mark.skip(
    reason="Python android/adb.py has no appium-adb client options "
    "(udid/executable/remoteAdbHost); MIDSCENE_ADB_PATH is read only by "
    "resolve_adb_executable()"
)
def test_uses_midscene_adb_settings_when_device_options_are_absent():
    """uses MIDSCENE_ADB settings when device options are absent"""
    pass


@pytest.mark.skip(
    reason="Python has no appium-adb createADB() Android-SDK resolution path"
)
def test_uses_appium_sdk_resolution_when_no_custom_executable_is_configured():
    """uses Appium SDK resolution when no custom executable is configured"""
    pass


@pytest.mark.skip(
    reason="Python has no appium-adb getSdkRootFromEnv()/SDK-to-PATH fallback "
    "branch or warning callback to assert on"
)
def test_falls_back_to_path_when_the_configured_android_sdk_cannot_resolve_adb():
    """falls back to PATH when the configured Android SDK cannot resolve adb"""
    pass


@pytest.mark.skip(
    reason="Python adb resolution is resolve_adb_executable() "
    "(explicit > MIDSCENE_ADB_PATH > PATH) with no SDK-root branch"
)
def test_preserves_the_path_fallback_when_no_android_sdk_root_is_configured():
    """preserves the PATH fallback when no Android SDK root is configured"""
    pass
