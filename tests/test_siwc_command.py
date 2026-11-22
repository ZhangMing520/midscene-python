"""Synced from upstream packages/cli/tests/unit-test/siwc-command.test.ts."""

import datetime
import json
import os
import re
import time
from pathlib import Path

import pytest

from midscene.cli import siwc_command as siwc_module
from midscene.cli.openai.credentials import (
    lock_credentials,
    read_registration,
    save_registration,
)
from midscene.cli.openai.errors import SiwcError
from midscene.cli.siwc_command import run_siwc_command

credentials = {
    "ext_agent_host_id": "urn:uuid:test-host",
    "client_id": "oaiapp_test",
    "subject": "test-user",
    "issuer": "https://auth.openai.com",
    "access_token": "test-access",
    "refresh_token": "test-refresh",
    "id_token": "test-id",
    "scopes": ["chatgpt.tokens.use.direct"],
    "expires_at": 2000000000000,
}


@pytest.fixture
def io():
    stdout = []
    stderr = []
    return {
        "stdout": stdout.append,
        "stderr": stderr.append,
        "out": stdout,
        "err": stderr,
    }


@pytest.fixture
def credentials_path(tmp_path):
    return str(tmp_path / "siwc.json")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    login_calls = []
    refresh_calls = []

    async def default_login(**options):
        login_calls.append(options)
        raise AssertionError("login_with_openai should not be called")

    async def default_refresh(saved):
        refresh_calls.append(saved)
        raise AssertionError("refresh_siwc_credentials should not be called")

    monkeypatch.setattr(siwc_module, "login_with_openai", default_login)
    monkeypatch.setattr(
        siwc_module, "refresh_siwc_credentials", default_refresh
    )
    yield {"login": login_calls, "refresh": refresh_calls}


def _parse_iso(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_saves_full_credentials_with_private_permissions_and_prints_only_the_access_token(
    monkeypatch, io, credentials_path
):
    """saves full credentials with private permissions and prints only the access token"""

    async def fake_login(**options):
        assert (
            read_registration(credentials_path)["ext_agent_host_id"]
            == options["host_id"]
        )
        options["on_authorization"]("https://auth.openai.com/test")
        return {**credentials, "ext_agent_host_id": options["host_id"]}

    monkeypatch.setattr(siwc_module, "login_with_openai", fake_login)

    assert (
        await run_siwc_command(["login", "--no-open"], io, credentials_path) == 0
    )

    saved = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
    assert saved["credentials"]["access_token"] == "test-access"
    assert "access_token" not in saved
    created = _parse_iso(saved["created_at"])
    updated = _parse_iso(saved["updated_at"])
    assert updated >= created
    assert io["out"] == ["test-access"]
    assert io["err"][0] == "🔄 Starting OpenAI SIWC login..."
    assert (
        "\nContinue with ChatGPT:\nhttps://auth.openai.com/test\n\n"
        "Waiting for authorization..." in "\n".join(io["err"])
    )
    assert (
        f"Full credentials are saved locally to:\n{credentials_path}"
        in io["err"][-1]
    )
    assert os.stat(credentials_path).st_mode & 0o777 == 0o600
    joined = "\n".join(io["err"])
    assert "Midscene does not collect your credentials." in joined
    assert "test-access" not in joined
    assert not Path(f"{credentials_path}.lock").exists()


@pytest.mark.asyncio
async def test_reuses_the_saved_client_and_host_on_login(
    monkeypatch, io, credentials_path, _no_network
):
    """reuses the saved client and host on login"""
    save_registration(credentials_path, credentials)
    login_calls = _no_network["login"]

    async def fake_login(**options):
        login_calls.append(options)
        return credentials

    monkeypatch.setattr(siwc_module, "login_with_openai", fake_login)

    assert (
        await run_siwc_command(["login", "--no-open"], io, credentials_path) == 0
    )
    assert login_calls[0]["client_id"] == credentials["client_id"]
    assert login_calls[0]["host_id"] == credentials["ext_agent_host_id"]


@pytest.mark.asyncio
async def test_rotates_stored_credentials_on_refresh_without_opening_login(
    monkeypatch, io, credentials_path, _no_network
):
    """rotates stored credentials on refresh without opening login"""
    created_at = "2026-01-01T00:00:00.000Z"
    Path(credentials_path).write_text(
        json.dumps(
            {
                "created_at": created_at,
                "updated_at": created_at,
                "credentials": credentials,
            }
        ),
        encoding="utf-8",
    )
    replacement = {
        **credentials,
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_at": int(time.time() * 1000) + 60 * 60_000,
    }

    async def fake_refresh(saved):
        return replacement

    monkeypatch.setattr(
        siwc_module, "refresh_siwc_credentials", fake_refresh
    )

    assert await run_siwc_command(["refresh"], io, credentials_path) == 0
    assert read_registration(credentials_path) == replacement
    saved = json.loads(Path(credentials_path).read_text(encoding="utf-8"))
    assert saved["created_at"] == created_at
    assert _parse_iso(saved["updated_at"]) > _parse_iso(created_at)
    assert io["out"] == [replacement["access_token"]]
    assert any(
        re.fullmatch(r"\nExpires at: .+ \(in 1 hour\)", message) for message in io["err"]
    )
    assert _no_network["login"] == []


@pytest.mark.asyncio
async def test_prints_login_diagnostics_and_releases_the_lock(
    monkeypatch, io, credentials_path
):
    """prints login diagnostics and releases the lock"""

    async def fake_login(**options):
        raise SiwcError(
            "Stage: Token exchange\nHTTP status: 400\nError: invalid_grant"
        )

    monkeypatch.setattr(siwc_module, "login_with_openai", fake_login)

    assert (
        await run_siwc_command(["login", "--no-open"], io, credentials_path) == 1
    )
    output = "\n".join(io["err"])
    assert "Stage: Token exchange" in output
    assert "HTTP status: 400" in output
    assert "Error: invalid_grant" in output
    assert io["out"] == []
    assert not Path(f"{credentials_path}.lock").exists()


@pytest.mark.asyncio
async def test_keeps_old_credentials_and_prints_original_failure_details(
    monkeypatch, io, credentials_path, _no_network
):
    """keeps old credentials and prints original failure details"""
    save_registration(credentials_path, credentials)
    original = Path(credentials_path).read_text(encoding="utf-8")

    async def fake_refresh(saved):
        raise Exception("refresh_token=secret")

    monkeypatch.setattr(
        siwc_module, "refresh_siwc_credentials", fake_refresh
    )

    assert await run_siwc_command(["refresh"], io, credentials_path) == 1
    assert read_registration(credentials_path) == credentials
    assert Path(credentials_path).read_text(encoding="utf-8") == original
    assert io["out"] == []
    assert "refresh_token=secret" in "\n".join(io["err"])


@pytest.mark.asyncio
async def test_does_not_replace_a_saved_account_with_a_different_identity(
    monkeypatch, io, credentials_path, _no_network
):
    """does not replace a saved account with a different identity"""
    save_registration(credentials_path, credentials)

    async def fake_login(**options):
        return {**credentials, "subject": "other-user"}

    monkeypatch.setattr(siwc_module, "login_with_openai", fake_login)

    assert (
        await run_siwc_command(["login", "--no-open"], io, credentials_path) == 1
    )
    assert read_registration(credentials_path) == credentials


@pytest.mark.asyncio
async def test_rejects_concurrent_commands_before_reading_or_refreshing_tokens(
    io, credentials_path, _no_network
):
    """rejects concurrent commands before reading or refreshing tokens"""
    unlock = await lock_credentials(credentials_path)
    try:
        assert await run_siwc_command(["refresh"], io, credentials_path) == 1
        assert _no_network["refresh"] == []
    finally:
        await unlock()


@pytest.mark.asyncio
async def test_requires_saved_credentials_for_refresh(
    io, credentials_path, _no_network
):
    """requires saved credentials for refresh"""
    assert await run_siwc_command(["refresh"], io, credentials_path) == 1
    assert _no_network["refresh"] == []


@pytest.mark.asyncio
async def test_rejects_the_old_flat_credentials_format(credentials_path):
    """rejects the old flat credentials format"""
    Path(credentials_path).write_text(
        json.dumps(credentials), encoding="utf-8"
    )
    with pytest.raises(SiwcError, match="Invalid local SIWC credentials file."):
        read_registration(credentials_path)


@pytest.mark.asyncio
async def test_rejects_invalid_options_before_authorization(
    io, credentials_path, _no_network
):
    """rejects invalid options before authorization"""
    for args in (
        ["login", "--port", "-1"],
        ["login", "--port"],
        ["login", "--port", "65536"],
        ["login", "--unknown"],
        ["refresh", "--no-open"],
        ["unknown"],
    ):
        assert await run_siwc_command(args, io, credentials_path) == 1
    assert _no_network["login"] == []


@pytest.mark.asyncio
async def test_shows_help_with_no_subcommand(
    io, credentials_path, _no_network
):
    """shows help with no subcommand"""
    assert await run_siwc_command([], io, credentials_path) == 0
    assert await run_siwc_command(["--help"], io, credentials_path) == 0
    assert "siwc refresh" in "\n".join(io["out"])
    assert _no_network["login"] == []
