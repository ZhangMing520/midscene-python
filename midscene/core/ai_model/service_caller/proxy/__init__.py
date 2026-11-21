"""Proxy support for model calls (upstream service-caller/proxy)."""

from midscene.core.ai_model.service_caller.proxy.proxy import (
    resolve_proxy_agent,
    sanitize_proxy_url,
)

__all__ = ["resolve_proxy_agent", "sanitize_proxy_url"]
