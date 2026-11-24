"""System One request preparation (upstream system-one/prepare-system-one.ts)."""

import json
from typing import Any
from urllib.parse import urlparse

from midscene.core.ai_model.service_caller.system_one.resolve_endpoint import (
    resolve_system_one_endpoint,
)
from midscene.core.ai_model.service_caller.system_one.schema import SystemOneError
from midscene.core.ai_model.service_caller.system_one.utils import (
    encode_system_one_images,
)


def prepare_system_one(
    config: dict[str, Any],
    request: dict[str, Any],
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    if not config.get("openaiApiKey"):
        raise SystemOneError("Jev requires MIDSCENE_*_MODEL_API_KEY")
    protocol = config.get("protocol")
    if protocol and protocol != "openai-chat":
        raise SystemOneError("Jev uses System One, not the Responses API")

    url = resolve_system_one_endpoint(config)
    is_openrouter = urlparse(url).hostname == "openrouter.ai"
    image_state, assets = encode_system_one_images(request.get("images"), is_openrouter)
    body: dict[str, Any] = {
        **(config.get("extraBody") or {}),
        "model": config.get("modelName"),
        "state": {**request.get("state", {}), **image_state},
        "questions": request.get("questions", {}),
    }
    if not is_openrouter and assets:
        body["assets"] = assets
    serialized_body = json.dumps(body, ensure_ascii=False)
    if len(serialized_body.encode("utf-8")) > 32 * 1024 * 1024:
        raise SystemOneError("Jev request exceeds the 32 MiB body limit")

    headers: dict[str, str] = {
        "Authorization": f"Bearer {config.get('openaiApiKey')}",
        "Content-Type": "application/json",
        "TypeSafe-Danger-Zone-Images": "true",
        "x-midscene-version": __import__("midscene").__version__,
    }
    if execution_id:
        headers["x-midscene-execution-id"] = execution_id
    extra_headers = (config.get("openaiExtraConfig") or {}).get("defaultHeaders")
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})

    return {
        "url": url,
        "body": serialized_body,
        "questions": request.get("questions", {}),
        "headers": headers,
        "proxy": config.get("httpProxy") or config.get("socksProxy"),
    }


__all__ = ["prepare_system_one"]
