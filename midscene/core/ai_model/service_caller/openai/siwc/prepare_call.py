"""Switch SIWC-auth runtimes onto api.openai.com (upstream prepare-call.ts)."""

from typing import Any, Optional, Tuple

from midscene.core.ai_model.service_caller.openai.siwc.token_manager import (
    siwc_token_manager,
)


async def prepare_siwc_call(
    model_runtime, options: Optional[dict] = None
) -> Tuple[Any, Optional[dict]]:
    """Build effective request settings without mutating the user's configuration."""
    if model_runtime.config.get("authMode") != "siwc":
        return model_runtime, options
    base_url = "https://api.openai.com/v1"
    api_key = await siwc_token_manager.get_access_token()
    from midscene.core.ai_model.models.registry import ModelRuntime

    new_config = {
        **model_runtime.config,
        "openaiBaseURL": base_url,
        "openaiApiKey": api_key,
        "protocol": "openai-responses",
        "streamMode": "stream",
    }
    return ModelRuntime(new_config, model_runtime.adapter), {
        **(options or {}),
        "stream": True,
    }
