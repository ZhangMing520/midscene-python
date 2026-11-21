"""SIWC credential persistence (upstream openai/siwc/credential-storage.ts).

Credentials are stored in ``~/.midscene/siwc.json`` with mode 0600 and
replaced atomically. The upstream browser/extension storage branch does not
apply to the Python SDK.
"""

from typing import Any, Dict
import json
import os
import uuid
from pathlib import Path

from midscene.core.ai_model.service_caller.openai.siwc.errors import SiwcError

SIWC_AUTH_STORAGE_KEY = "midscene-siwc-auth"

REAUTHORIZATION_HINT = (
    'Run "midscene model siwc login" to sign in again. '
    "See https://midscenejs.com/chatgpt-subscription.html"
)


def _credentials_path() -> Path:
    return Path.home() / ".midscene" / "siwc.json"


def _read_credentials() -> Dict[str, Any]:
    path = _credentials_path()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SiwcError(
            f"SIWC credentials not found at {path}. {REAUTHORIZATION_HINT}"
        )
    except OSError:
        raise SiwcError(f"Unable to read SIWC credentials at {path}.")
    try:
        record = json.loads(content)
    except json.JSONDecodeError:
        raise SiwcError(f"Invalid JSON in SIWC credentials at {path}.")
    credentials = record.get("credentials") or {}
    access_token = credentials.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise SiwcError(f"Missing access token in {path}. {REAUTHORIZATION_HINT}")
    return record


def _save_credentials(record: Dict[str, Any]) -> None:
    """Replace atomically so a reader never sees a partially written file."""
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with open(
            temporary,
            "w",
            encoding="utf-8",
            opener=lambda p, flags: os.open(p, flags, 0o600),
        ) as f:
            f.write(json.dumps(record, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class SiwcCredentialStorage:
    """File-backed credential storage (upstream getCredentialStorage)."""

    reauthorization_hint = REAUTHORIZATION_HINT

    def read(self) -> Dict[str, Any]:
        return _read_credentials()

    def save(self, record: Dict[str, Any]) -> None:
        _save_credentials(record)


def get_credential_storage() -> SiwcCredentialStorage:
    return SiwcCredentialStorage()
