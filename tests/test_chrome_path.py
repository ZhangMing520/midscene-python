"""Synced from upstream ``packages/shared/tests/unit-test/chrome-path.test.ts``."""

import pytest

from midscene.shared.agent_tools import chrome_path


@pytest.fixture(autouse=True)
def _reset_chrome_path_state(monkeypatch):
    monkeypatch.setattr(chrome_path, "_cached_system_chrome_path", None)
    monkeypatch.setattr(chrome_path, "_has_warned_legacy_chrome_path", False)
    monkeypatch.delenv(chrome_path.MIDSCENE_CHROME_PATH, raising=False)
    monkeypatch.delenv(chrome_path.MIDSCENE_MCP_CHROME_PATH, raising=False)


def _use_platform(monkeypatch, platform):
    monkeypatch.setattr(chrome_path.sys, "platform", platform)


def test_should_return_macos_chrome_path(monkeypatch):
    """should return macOS Chrome path"""
    _use_platform(monkeypatch, "darwin")
    mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda path: path == mac_path)

    assert chrome_path.get_system_chrome_path() == mac_path


def test_should_prefer_opt_google_chrome_chrome_on_linux(monkeypatch):
    """should prefer /opt/google/chrome/chrome on Linux"""
    _use_platform(monkeypatch, "linux")
    opt_path = "/opt/google/chrome/chrome"
    usr_path = "/usr/bin/google-chrome"
    monkeypatch.setattr(
        chrome_path.os.path,
        "exists",
        lambda path: path in (opt_path, usr_path),
    )

    assert chrome_path.get_system_chrome_path() == opt_path


def test_should_fallback_to_usr_bin_paths_on_linux(monkeypatch):
    """should fallback to /usr/bin paths on Linux"""
    _use_platform(monkeypatch, "linux")
    linux_path = "/usr/bin/google-chrome"
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda path: path == linux_path)

    assert chrome_path.get_system_chrome_path() == linux_path


def test_should_return_windows_chrome_path(monkeypatch):
    """should return Windows Chrome path"""
    _use_platform(monkeypatch, "win32")
    win_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda path: path == win_path)

    assert chrome_path.get_system_chrome_path() == win_path


def test_should_return_undefined_when_no_chrome_found(monkeypatch):
    """should return undefined when no Chrome found"""
    _use_platform(monkeypatch, "linux")
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda _path: False)

    assert chrome_path.get_system_chrome_path() is None


def test_should_cache_the_resolved_chrome_path(monkeypatch):
    """should cache the resolved Chrome path"""
    _use_platform(monkeypatch, "linux")
    opt_path = "/opt/google/chrome/chrome"
    calls = []

    def fake_exists(path):
        calls.append(path)
        return path == opt_path

    monkeypatch.setattr(chrome_path.os.path, "exists", fake_exists)

    assert chrome_path.get_system_chrome_path() == opt_path
    assert calls

    calls.clear()
    assert chrome_path.get_system_chrome_path() == opt_path
    assert calls == []


def test_should_not_cache_when_chrome_is_not_found(monkeypatch):
    """should not cache when Chrome is not found"""
    _use_platform(monkeypatch, "linux")
    calls = []

    def fake_exists(path):
        calls.append(path)
        return False

    monkeypatch.setattr(chrome_path.os.path, "exists", fake_exists)

    assert chrome_path.get_system_chrome_path() is None

    calls.clear()
    assert chrome_path.get_system_chrome_path() is None
    assert calls


def test_should_return_env_chrome_path_when_valid(monkeypatch):
    """should return env chrome path when valid"""
    custom_path = "/custom/chrome/path"
    monkeypatch.setenv(chrome_path.MIDSCENE_CHROME_PATH, custom_path)
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda _path: True)

    assert chrome_path.resolve_chrome_path() == custom_path


def test_should_fallback_to_legacy_mcp_chrome_path_when_primary_env_is_unset(
    monkeypatch,
):
    """should fallback to legacy MCP chrome path when primary env is unset"""
    legacy_path = "/legacy/chrome/path"
    monkeypatch.setenv(chrome_path.MIDSCENE_MCP_CHROME_PATH, legacy_path)
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda _path: True)

    assert chrome_path.resolve_chrome_path() == legacy_path


def test_should_fallback_to_system_path_when_env_is_auto(monkeypatch):
    """should fallback to system path when env is auto"""
    _use_platform(monkeypatch, "linux")
    monkeypatch.setenv(chrome_path.MIDSCENE_CHROME_PATH, "auto")
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda _path: False)

    with pytest.raises(RuntimeError, match="Chrome not found"):
        chrome_path.resolve_chrome_path()


def test_should_throw_when_no_chrome_found(monkeypatch):
    """should throw when no Chrome found"""
    _use_platform(monkeypatch, "linux")
    monkeypatch.setattr(chrome_path.os.path, "exists", lambda _path: False)

    with pytest.raises(RuntimeError, match="Chrome not found"):
        chrome_path.resolve_chrome_path()
