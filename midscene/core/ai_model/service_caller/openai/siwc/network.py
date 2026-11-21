"""SIWC HTTP/JWKS access (upstream openai/siwc/network.ts)."""

from typing import Any, Dict, List, Optional, Tuple, TypedDict
import os
import time

import httpx
from loguru import logger

from midscene.core.ai_model.service_caller.openai.siwc.errors import SiwcError

try:
    import jwt as pyjwt

    _HAS_PYJWT = True
except ImportError:  # pragma: no cover
    _HAS_PYJWT = False

ISSUER = "https://auth.openai.com"


class SiwcProxyConfig(TypedDict, total=False):
    httpProxy: Optional[str]
    socksProxy: Optional[str]


def _siwc_proxy(proxy: Optional[SiwcProxyConfig] = None) -> Optional[str]:
    """Resolve the proxy for SIWC requests (upstream fetchSiwc).

    Explicit ``{"httpProxy", "socksProxy"}`` config wins over
    MIDSCENE_MODEL_HTTP_PROXY / MIDSCENE_MODEL_SOCKS_PROXY; an HTTP proxy
    takes precedence over a SOCKS proxy."""
    if proxy is None:
        proxy = {
            "httpProxy": (os.environ.get("MIDSCENE_MODEL_HTTP_PROXY") or "").strip()
            or None,
            "socksProxy": (os.environ.get("MIDSCENE_MODEL_SOCKS_PROXY") or "").strip()
            or None,
        }
    return proxy.get("httpProxy") or proxy.get("socksProxy") or None


_JWKS_TTL_SECONDS = 3600.0
_jwks_cache: Optional[Dict[str, Any]] = None


def _select_jwk(keys: List[Any], kid: Optional[str]) -> List[Any]:
    if kid:
        return [key for key in keys if key.key_id == kid]
    # Without a kid only a single-key set is unambiguous.
    return list(keys) if len(keys) == 1 else []


async def _fetch_jwks(
    proxy: Optional[SiwcProxyConfig] = None,
) -> List[Any]:
    async with httpx.AsyncClient(
        timeout=30.0, proxy=_siwc_proxy(proxy)
    ) as client:
        jwks_response = await client.get(
            f"{ISSUER}/.well-known/jwks.json", follow_redirects=False
        )
    if jwks_response.status_code >= 400:
        raise SiwcError(
            f"Failed to fetch OpenAI JWKS: HTTP {jwks_response.status_code}"
        )
    return pyjwt.PyJWKSet.from_dict(jwks_response.json()).keys


async def _load_jwks(
    proxy: Optional[SiwcProxyConfig] = None,
    force: bool = False,
) -> List[Any]:
    """Signing keys from the JWKS, cached like PyJWKClient did."""
    global _jwks_cache
    if not force and _jwks_cache is not None:
        if time.time() - _jwks_cache["fetched_at"] <= _JWKS_TTL_SECONDS:
            return _jwks_cache["keys"]
    keys = await _fetch_jwks(proxy)
    _jwks_cache = {"fetched_at": time.time(), "keys": keys}
    return keys


async def _verify_id_token(
    id_token: str,
    audience: str,
    required_claims: Tuple[str, ...],
    proxy: Optional[SiwcProxyConfig] = None,
):
    if not _HAS_PYJWT:
        logger.warning(
            "PyJWT is not installed; skipping SIWC id-token signature verification"
        )
        return {}
    try:
        kid = pyjwt.get_unverified_header(id_token).get("kid")
        keys = await _load_jwks(proxy)
        candidates = _select_jwk(keys, kid)
        if not candidates and kid:
            # The signing key may have rotated since the cache was filled.
            keys = await _load_jwks(proxy, force=True)
            candidates = _select_jwk(keys, kid)
        if not candidates:
            raise SiwcError("No matching signing key in OpenAI JWKS.")
        # clockTolerance=inf upstream: CI machines may have skewed clocks.
        payload = pyjwt.decode(
            id_token,
            candidates[0].key,
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
        raise SiwcError(f"Stage: ID token verification\n{e}") from e
