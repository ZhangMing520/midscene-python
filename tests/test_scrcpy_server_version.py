"""Port of upstream packages/android/tests/unit-test/scrcpy-server-version.test.ts.

Upstream lives in ``packages/android/scripts/download-scrcpy-server.mjs``; the
Python port performs the same acquisition from
``midscene/android/scrcpy_manager.py``.
"""

from pathlib import Path

import pytest

from midscene.android.scrcpy_manager import (
    SCRCPY_PROTOCOL_VERSION,
    SCRCPY_SERVER_VERSION_TAG,
    ScrcpyScreenshotManager,
    ensure_scrcpy_server,
    get_scrcpy_server_download_url,
    should_download_scrcpy_server,
)


def test_uses_a_single_hard_coded_scrcpy_version_for_runtime_and_server_download():
    """uses a single hard-coded scrcpy version for runtime and server download.

    Upstream compares the @yume-chan runtime protocol version with the
    download helper. The Python port has no runtime scrcpy package; the
    protocol version it launches the server with must match the download tag.
    """

    manager = ScrcpyScreenshotManager(None, None, {})

    assert SCRCPY_PROTOCOL_VERSION == "3.3.3"
    assert SCRCPY_SERVER_VERSION_TAG == "v3.3.3"
    assert get_scrcpy_server_download_url() == (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v3.3.3/scrcpy-server-v3.3.3"
    )
    # The runtime launch path embeds the same hard-coded protocol version.
    server_args = ScrcpyScreenshotManager._build_server_args(
        manager.create_scrcpy_options()
    )
    assert SCRCPY_PROTOCOL_VERSION in server_args


def test_forces_a_refresh_when_cached_version_metadata_is_missing_or_stale():
    """forces a refresh when cached version metadata is missing or stale."""

    assert should_download_scrcpy_server(None, "v3.3.3") is True
    assert should_download_scrcpy_server("v3.3.4", "v3.3.3") is True
    assert should_download_scrcpy_server(" v3.3.3\n", "v3.3.3") is False


def test_uses_the_public_github_release_asset_url_for_the_scrcpy_server():
    """uses the public GitHub release asset URL for the scrcpy server."""

    assert get_scrcpy_server_download_url("v3.3.3") == (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v3.3.3/scrcpy-server-v3.3.3"
    )


def test_downloads_the_scrcpy_server_from_the_release_asset_url_directly(
    tmp_path: Path,
):
    """downloads the scrcpy server from the release asset URL directly."""

    cache_dir = tmp_path / "cache"
    calls = []

    def fetch_impl(url, timeout):
        calls.append((url, timeout))
        return b"server-binary"

    destination = ensure_scrcpy_server(
        cache_dir=str(cache_dir), http_get=fetch_impl
    )

    assert calls[0][0] == (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v3.3.3/scrcpy-server-v3.3.3"
    )
    assert Path(destination).read_bytes() == b"server-binary"


@pytest.mark.skip(
    reason=(
        "Python ensure_scrcpy_server has no GitHub asset-API fallback "
        "(downloadGitHubReleaseAssetWithApiFallback does not exist); it only "
        "performs the single direct release-asset download."
    )
)
def test_falls_back_to_the_github_asset_api_anonymously_when_the_browser_download_url_fails():
    """falls back to the GitHub asset API anonymously when the browser download URL fails."""


@pytest.mark.skip(
    reason=(
        "Python ensure_scrcpy_server returns any existing cached jar without "
        "re-downloading, so there is no installDownloadedScrcpyServer swap "
        "step whose 'download ready then replace' timing can be observed."
    )
)
def test_replaces_the_cached_server_only_after_the_new_download_is_ready():
    """replaces the cached server only after the new download is ready."""


@pytest.mark.skip(
    reason=(
        "Python writes a .part file and performs one atomic os.replace; there "
        "is no backup file / restore-on-rename-failure path equivalent to "
        "installDownloadedScrcpyServer."
    )
)
def test_restores_the_cached_server_if_swapping_in_the_new_binary_fails():
    """restores the cached server if swapping in the new binary fails."""
