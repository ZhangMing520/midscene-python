"""Proxy resolution for model calls (upstream service-caller/proxy/proxy.ts).

Upstream builds an undici ``ProxyAgent``; httpx accepts proxy URLs directly, so
this module validates/normalizes the configured URL and hands it to httpx.
"""

from typing import Optional
from urllib.parse import urlparse, urlunparse

from loguru import logger


def sanitize_proxy_url(url: str) -> str:
    """Hide the password while keeping the username for diagnostics."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(f":{parsed.password}@", "****@")
            return urlunparse(parsed._replace(netloc=netloc))
        return url
    except ValueError:
        return url


def resolve_proxy_agent(
    socks_proxy: Optional[str] = None,
    http_proxy: Optional[str] = None,
) -> Optional[str]:
    """Return the proxy URL for httpx, preferring HTTP over SOCKS."""
    if http_proxy:
        logger.debug(f"using http proxy {sanitize_proxy_url(http_proxy)}")
        return http_proxy
    if socks_proxy:
        logger.debug(f"using socks proxy {sanitize_proxy_url(socks_proxy)}")
        parsed = urlparse(socks_proxy)
        if not parsed.hostname:
            raise ValueError(
                "SOCKS proxy URL must include a valid hostname"
            )
        try:
            port = int(parsed.port or 0)
        except ValueError:
            port = 0
        if port <= 0:
            raise ValueError("SOCKS proxy URL must include a valid port")
        return socks_proxy
    return None


def create_proxy_agent_if_needed(
    socks_proxy: Optional[str] = None,
    http_proxy: Optional[str] = None,
) -> Optional[str]:
    """Return the proxy URL handed to httpx (upstream ProxyAgent equivalent).

    httpx accepts proxy URLs directly, so this validates and normalizes the
    configured URL instead of constructing an undici dispatcher.
    """
    return resolve_proxy_agent(socks_proxy=socks_proxy, http_proxy=http_proxy)


__all__ = [
    "create_proxy_agent_if_needed",
    "resolve_proxy_agent",
    "sanitize_proxy_url",
]
