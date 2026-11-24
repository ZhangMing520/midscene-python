"""Default Codex app-server params (upstream model-adapter/codex-app-server.ts)."""

from typing import Any

MIDSCENE_CODEX_APP_SERVER_DEFAULTS: dict[str, Any] = {"effort": "none"}

_CODEX_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}


def build_default_codex_app_server_params(
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Default ``buildCodexAppServerParams`` when an adapter has no override."""
    user_config = (input_data or {}).get("userConfig") or {}
    if user_config.get("reasoningEnabled") is not True:
        return {"config": dict(MIDSCENE_CODEX_APP_SERVER_DEFAULTS)}

    effort = (user_config.get("reasoningEffort") or "").strip().lower()
    return {
        "config": {"effort": effort if effort in _CODEX_REASONING_EFFORTS else "medium"}
    }


__all__ = [
    "MIDSCENE_CODEX_APP_SERVER_DEFAULTS",
    "build_default_codex_app_server_params",
]
