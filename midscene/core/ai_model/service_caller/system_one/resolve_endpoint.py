"""System One endpoint resolution (upstream system-one/resolve-endpoint.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.service_caller.system_one.schema import SystemOneError


def resolve_system_one_endpoint(config: Dict[str, Any]) -> str:
    endpoint = config.get("endpoint")
    if endpoint:
        return endpoint
    base_url = config.get("openaiBaseURL")
    if not base_url:
        raise SystemOneError(
            "When using the System One API, you must provide "
            "MIDSCENE_*_MODEL_ENDPOINT or MIDSCENE_*_MODEL_BASE_URL."
        )
    return base_url.rstrip("/") + "/systemone"


__all__ = ["resolve_system_one_endpoint"]
