"""SIWC OAuth authorization flow (upstream openai/siwc/authorization.ts)."""

from typing import Any, Dict, Optional, TypedDict
import base64
import hashlib
import os
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from midscene.core.ai_model.service_caller.openai.siwc import network
from midscene.core.ai_model.service_caller.openai.siwc.errors import (
    SiwcError,
    token_response_error,
    with_siwc_stage,
)

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
DEFAULT_DYNAMIC_CLIENT_ID = "dynamic_agent_client"


class SiwcLoginAttempt(TypedDict):
    """Pending OAuth login state (upstream SiwcLoginAttempt)."""

    host_id: str
    redirect_uri: str
    client_id: Optional[str]
    state: str
    nonce: str
    verifier: str
    expires_at: float


def _base64url(bytes_data: bytes) -> str:
    return base64.urlsafe_b64encode(bytes_data).rstrip(b"=").decode("ascii")


def create_siwc_authorization(
    host_id: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
    agent_name: str = "Midscene Python",
) -> Dict[str, Any]:
    """Build the OAuth authorization URL (PKCE + state + nonce)."""
    random = lambda: _base64url(os.urandom(32))  # noqa: E731
    attempt: SiwcLoginAttempt = {
        "host_id": host_id,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "state": random(),
        "nonce": random(),
        "verifier": random(),
        "expires_at": time.time() + 5 * 60,
    }
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
    return {
        "attempt": attempt,
        "url": f"{ISSUER}/api/accounts/authorize?{urlencode(params)}",
    }


def parse_siwc_callback(
    callback_url: str, attempt: Dict[str, Any]
) -> Optional[Dict[str, str]]:
    callback = urlparse(callback_url)
    expected = urlparse(attempt["redirect_uri"])
    if (callback.scheme, callback.netloc, callback.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        return None

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
    attempt: Dict[str, Any],
    callback: Dict[str, str],
    proxy: Optional[network.SiwcProxyConfig] = None,
) -> Dict[str, Any]:
    """Exchange the OAuth code for tokens and verify the ID token."""
    async with httpx.AsyncClient(
        timeout=30.0, proxy=network._siwc_proxy(proxy)
    ) as client:

        async def exchange() -> httpx.Response:
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
            if response.status_code >= 400:
                raise await token_response_error(response)
            return response

        response = await with_siwc_stage("Token exchange", exchange)

    tokens = await with_siwc_stage(
        "Token response parsing", lambda: _json_body(response)
    )
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

    payload = await with_siwc_stage(
        "ID token verification",
        lambda: network._verify_id_token(
            tokens["id_token"],
            callback["client_id"],
            ("sub", "exp", "iat", "nonce"),
            proxy,
        ),
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


async def _json_body(response: httpx.Response) -> Any:
    return response.json()
