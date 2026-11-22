"""SIWC OAuth refresh flow (upstream openai/siwc/refresh.ts)."""

from typing import Any, Dict, Optional, TypedDict
import time

import httpx

from midscene.core.ai_model.service_caller.openai.siwc import network
from midscene.core.ai_model.service_caller.openai.siwc.errors import (
    SiwcError,
    token_response_error,
    with_siwc_stage,
)

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"


class RefreshableCredentials(TypedDict, total=False):
    client_id: Optional[str]
    refresh_token: Optional[str]
    subject: Optional[str]
    id_token: Optional[str]


async def refresh_siwc_credentials(
    saved: Dict[str, Any],
    signal: Any = None,
    dependencies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if signal is not None and hasattr(signal, "throw_if_aborted"):
        signal.throw_if_aborted()
    proxy = (
        dependencies.get("proxy")
        if isinstance(dependencies, dict)
        else None
    )
    client_id = saved.get("client_id")
    refresh_token = saved.get("refresh_token")
    if not client_id or not refresh_token:
        raise SiwcError("Missing client ID or refresh token.")

    async with httpx.AsyncClient(
        timeout=30.0, proxy=network._siwc_proxy(proxy)
    ) as client:

        async def exchange() -> httpx.Response:
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
            if response.status_code >= 400:
                raise await token_response_error(response)
            return response

        response = await with_siwc_stage("Token refresh", exchange)

    tokens = await with_siwc_stage(
        "Refresh response parsing", lambda: _json_body(response)
    )
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
        payload = await with_siwc_stage(
            "ID token verification",
            lambda: network._verify_id_token(
                tokens["id_token"], client_id, ("sub", "exp", "iat"), proxy
            ),
        )
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


async def _json_body(response: httpx.Response) -> Any:
    return response.json()
