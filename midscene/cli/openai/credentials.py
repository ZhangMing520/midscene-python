"""CLI credential storage access (upstream packages/cli/src/openai/credentials.ts)."""

import datetime
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from midscene.core.ai_model.service_caller.openai.siwc.credential_storage import (
    REAUTHORIZATION_HINT,
    SIWC_AUTH_STORAGE_KEY,
    _credentials_path,
    _read_credentials,
    _save_credentials,
    get_credential_storage,
)
from midscene.core.ai_model.service_caller.openai.siwc.errors import SiwcError

OpenAICredentials = dict[str, Any]
Registration = dict[str, Any]

INVALID_REGISTRATION_MESSAGE = "Invalid local SIWC credentials file."


def default_credentials_path() -> str:
    return str(_credentials_path())


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _read_record(path: str) -> dict[str, Any] | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        record = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SiwcError(INVALID_REGISTRATION_MESSAGE) from error
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("credentials"), dict)
        or not isinstance(record.get("created_at"), str)
        or not isinstance(record.get("updated_at"), str)
    ):
        raise SiwcError(INVALID_REGISTRATION_MESSAGE)
    return record


def read_registration(path: str) -> dict[str, Any] | None:
    """Return the saved credentials, or None when no registration exists."""
    record = _read_record(path)
    return record["credentials"] if record else None


def save_registration(path: str, credentials: dict[str, Any]) -> None:
    """Persist credentials atomically with 0600 permissions."""
    existing = _read_record(path)
    now = _now_iso()
    record = {
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "credentials": credentials,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        with open(
            temporary,
            "w",
            encoding="utf-8",
            opener=lambda p, flags: os.open(p, flags, 0o600),
        ) as handle:
            handle.write(json.dumps(record, indent=2) + "\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def require_credentials(saved: dict[str, Any] | None) -> dict[str, Any]:
    if not saved or not saved.get("refresh_token"):
        raise SiwcError(
            'No saved SIWC credentials. Run "midscene model siwc login" first.'
        )
    return saved


async def lock_credentials(path: str) -> Callable[[], Awaitable[None]]:
    """Acquire the per-credentials-file lock; returns an async unlock callable."""
    lock_path = f"{path}.lock"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise SiwcError(
            "Another midscene model siwc command is already running."
        ) from error
    os.close(descriptor)

    async def unlock() -> None:
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass

    return unlock


__all__ = [
    "INVALID_REGISTRATION_MESSAGE",
    "OpenAICredentials",
    "REAUTHORIZATION_HINT",
    "Registration",
    "SIWC_AUTH_STORAGE_KEY",
    "_credentials_path",
    "_read_credentials",
    "_save_credentials",
    "default_credentials_path",
    "get_credential_storage",
    "lock_credentials",
    "read_registration",
    "require_credentials",
    "save_registration",
]
