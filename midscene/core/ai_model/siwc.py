"""SIWC (Sign-In with ChatGPT) auth mode for OpenAI models.

Synced from upstream packages/core/src/ai-model/service-caller/openai/siwc/*
and packages/cli/src/openai/login.ts. Credentials are stored in
`~/.midscene/siwc.json` (mode 0600). ID-token verification uses PyJWT with
OpenAI's remote JWKS.
"""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
from loguru import logger

try:
    import jwt as pyjwt
    from jwt import PyJWKClient

    _HAS_PYJWT = True
except ImportError:  # pragma: no cover
    _HAS_PYJWT = False

SIWC_AUTH_STORAGE_KEY = "midscene-siwc-auth"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
DEFAULT_DYNAMIC_CLIENT_ID = "dynamic_agent_client"

REAUTHORIZATION_HINT = (
    'Run "midscene model siwc login" to sign in again. '
    "See https://midscenejs.com/chatgpt-subscription.html"
)


class SiwcError(Exception):
    pass


class SiwcTokenExpiredError(Exception):
    """Signals an expired SIWC token that may be refreshed before replaying."""


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
        with open(temporary, "w", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write(json.dumps(record, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _with_siwc_stage(stage: str, error: BaseException) -> SiwcError:
    return SiwcError(f"Stage: {stage}\n{error}")


async def _token_response_error(response: httpx.Response) -> SiwcError:
    return SiwcError(
        f"HTTP status: {response.status_code}\nResponse body: {response.text}"
    )


def _verify_id_token(id_token: str, audience: str, required_claims: Tuple[str, ...]):
    if not _HAS_PYJWT:
        logger.warning(
            "PyJWT is not installed; skipping SIWC id-token signature verification"
        )
        return {}
    try:
        jwks_client = PyJWKClient(f"{ISSUER}/.well-known/jwks.json")
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        # clockTolerance=inf upstream: CI machines may have skewed clocks.
        payload = pyjwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=audience,
            options={
                "verify_exp": False,
                "verify_nbf": False,
                "require": list(required_claims),
            },
        )
        return payload
    except Exception as e:
        raise _with_siwc_stage("ID token verification", e)


# ---------------------------------------------------------------------------
# Refresh (refresh.ts)
# ---------------------------------------------------------------------------

async def refresh_siwc_credentials(saved: Dict[str, Any]) -> Dict[str, Any]:
    client_id = saved.get("client_id")
    refresh_token = saved.get("refresh_token")
    if not client_id or not refresh_token:
        raise SiwcError("Missing client ID or refresh token.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{ISSUER}/api/accounts/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "resource": RESOURCE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        except httpx.HTTPError as e:
            raise _with_siwc_stage("Token refresh", e)
    if response.status_code >= 400:
        raise await _token_response_error(response)

    tokens = response.json()
    if (
        not isinstance(tokens, dict)
        or not isinstance(tokens.get("access_token"), str)
        or not tokens["access_token"].strip()
        or not isinstance(tokens.get("refresh_token"), str)
        or not tokens["refresh_token"].strip()
        or not isinstance(tokens.get("expires_in"), (int, float))
        or tokens["expires_in"] <= 0
        or not isinstance(tokens.get("token_type"), str)
        or tokens["token_type"].lower() != "bearer"
        or not isinstance(tokens.get("scope"), str)
    ):
        raise SiwcError("OpenAI returned an invalid refresh response.")

    scopes = tokens["scope"].split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise SiwcError("ChatGPT plan usage is no longer authorized.")

    if tokens.get("id_token") is not None:
        if not isinstance(tokens["id_token"], str) or not tokens["id_token"]:
            raise SiwcError("Invalid refreshed ID token.")
        payload = _verify_id_token(tokens["id_token"], client_id, ("sub", "exp", "iat"))
        if payload and payload.get("sub") != saved.get("subject"):
            raise SiwcError("Refreshed identity does not match the saved account.")

    return {
        **saved,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "id_token": tokens.get("id_token") or saved.get("id_token"),
        "scopes": scopes,
        "expires_at": int(time.time() * 1000 + tokens["expires_in"] * 1000),
    }


class SiwcTokenManager:
    """Read/refresh stored SIWC credentials; refreshes are shared."""

    def __init__(self):
        self._pending_refresh: Optional[asyncio.Task] = None

    async def get_access_token(self) -> str:
        record = await asyncio.to_thread(_read_credentials)
        # Let the server reject expired tokens instead of trusting local clocks.
        return record["credentials"]["access_token"]

    def refresh_access_token(self, previous_access_token: str) -> "asyncio.Task":
        if self._pending_refresh is None:
            self._pending_refresh = asyncio.create_task(
                self._refresh_and_save(previous_access_token)
            )
            self._pending_refresh.add_done_callback(
                lambda _t: setattr(self, "_pending_refresh", None)
            )
        return self._pending_refresh

    async def _refresh_and_save(self, previous_access_token: str) -> str:
        record = await asyncio.to_thread(_read_credentials)
        saved = record.get("credentials", {})
        if saved.get("access_token") != previous_access_token:
            return saved["access_token"]
        try:
            credentials = await refresh_siwc_credentials(saved)
        except Exception as cause:
            raise SiwcError(
                f"Unable to refresh SIWC credentials: {cause} {REAUTHORIZATION_HINT}"
            ) from cause
        await asyncio.to_thread(
            _save_credentials,
            {**record, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "credentials": credentials},
        )
        return credentials["access_token"]


siwc_token_manager = SiwcTokenManager()


async def prepare_siwc_call(model_runtime) -> Tuple[Any, Optional[dict]]:
    """Switch a siwc-auth model runtime onto api.openai.com with the stored
    token (upstream prepareSiwcCall). Returns (runtime, options)."""
    if model_runtime.config.get("authMode") != "siwc":
        return model_runtime, None
    base_url = "https://api.openai.com/v1"
    api_key = await siwc_token_manager.get_access_token()
    from .adapters import ModelRuntime

    new_config = {
        **model_runtime.config,
        "openaiBaseURL": base_url,
        "openaiApiKey": api_key,
        "protocol": "openai-responses",
        "streamMode": "stream",
    }
    return ModelRuntime(new_config, model_runtime.adapter), {"stream": True}


# ---------------------------------------------------------------------------
# Login flow (authorization.ts + cli/openai/login.ts)
# ---------------------------------------------------------------------------

def _base64url(bytes_data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(bytes_data).rstrip(b"=").decode("ascii")


def create_siwc_authorization(
    host_id: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    agent_name: str = "Midscene Python",
) -> Dict[str, Any]:
    """Build the OAuth authorization URL (PKCE + state + nonce)."""
    random = lambda: _base64url(os.urandom(32))  # noqa: E731
    attempt = {
        "host_id": host_id,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "state": random(),
        "nonce": random(),
        "verifier": random(),
        "expires_at": time.time() + 5 * 60,
    }
    import hashlib

    challenge = _base64url(hashlib.sha256(attempt["verifier"].encode()).digest())
    params = {
        "client_id": client_id or DEFAULT_DYNAMIC_CLIENT_ID,
        **({} if client_id else {"agent_name_hint": agent_name}),
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": (
            "openid profile email offline_access resource.invoke "
            "chatgpt.tokens.use.direct"
        ),
        "resource": RESOURCE,
        "state": attempt["state"],
        "nonce": attempt["nonce"],
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return {"attempt": attempt, "url": f"{ISSUER}/api/accounts/authorize?{urlencode(params)}"}


def parse_siwc_callback(callback_url: str, attempt: Dict[str, Any]) -> Optional[Dict[str, str]]:
    callback = urlparse(callback_url)
    expected = urlparse(attempt["redirect_uri"])
    if (callback.scheme, callback.netloc, callback.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        return None

    from urllib.parse import parse_qs

    params = parse_qs(callback.query)
    states = params.get("state", [])
    if len(states) != 1 or states[0] != attempt["state"]:
        return None
    if time.time() >= attempt["expires_at"]:
        raise SiwcError("Authorization timed out. Start authorization again.")
    if "error" in params:
        raise SiwcError(
            "OpenAI authorization failed: "
            f"{params.get('error_description', params.get('error', [''])[0])}"
        )
    codes = params.get("code", [])
    code = codes[0] if codes else None
    client_ids = params.get("client_id", [])
    client_id = client_ids[0] if client_ids else attempt.get("client_id")
    if (
        not code
        or not client_id
        or client_id == DEFAULT_DYNAMIC_CLIENT_ID
        or len(codes) != 1
        or len(client_ids) > 1
        or (attempt.get("client_id") and client_id != attempt["client_id"])
    ):
        raise SiwcError("Invalid OpenAI authorization callback.")
    return {"code": code, "client_id": client_id}


async def exchange_siwc_code(
    attempt: Dict[str, Any], callback: Dict[str, str]
) -> Dict[str, Any]:
    """Exchange the OAuth code for tokens and verify the ID token."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{ISSUER}/api/accounts/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": callback["client_id"],
                    "code": callback["code"],
                    "code_verifier": attempt["verifier"],
                    "redirect_uri": attempt["redirect_uri"],
                    "resource": RESOURCE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        except httpx.HTTPError as e:
            raise _with_siwc_stage("Token exchange", e)
    if response.status_code >= 400:
        raise await _token_response_error(response)

    tokens = response.json()
    if (
        not isinstance(tokens, dict)
        or not tokens.get("access_token")
        or not tokens.get("refresh_token")
        or not isinstance(tokens.get("id_token"), str)
        or not isinstance(tokens.get("scope"), str)
        or not isinstance(tokens.get("expires_in"), (int, float))
        or tokens["expires_in"] <= 0
        or not isinstance(tokens.get("token_type"), str)
        or tokens["token_type"].lower() != "bearer"
    ):
        raise SiwcError("OpenAI returned an invalid token response.")
    scopes = tokens["scope"].split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise SiwcError("ChatGPT plan usage was not authorized.")

    payload = _verify_id_token(
        tokens["id_token"], callback["client_id"], ("sub", "exp", "iat", "nonce")
    )
    if payload.get("nonce") != attempt["nonce"] or not payload.get("sub"):
        raise SiwcError("OpenAI login identity or nonce did not match.")
    return {
        **({"email": payload["email"]} if isinstance(payload.get("email"), str) else {}),
        "ext_agent_host_id": attempt["host_id"],
        "client_id": callback["client_id"],
        "subject": payload["sub"],
        "issuer": ISSUER,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "id_token": tokens["id_token"],
        "scopes": scopes,
        "expires_at": int(time.time() * 1000 + tokens["expires_in"] * 1000),
    }


__all__ = [
    "SiwcError",
    "SiwcTokenExpiredError",
    "siwc_token_manager",
    "prepare_siwc_call",
    "create_siwc_authorization",
    "parse_siwc_callback",
    "exchange_siwc_code",
    "refresh_siwc_credentials",
    "REAUTHORIZATION_HINT",
]
