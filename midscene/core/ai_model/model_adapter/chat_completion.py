"""Chat-completion request helpers (upstream ai-model/model-adapter/chat-completion.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

MIDSCENE_DEFAULT_TEMPERATURE = 0.0


def _json_object_config(
    user_config: ModelRequestUserConfig, expected_json_object_response: bool
) -> Dict[str, Any]:
    if user_config.get("responseFormat") != "none" and expected_json_object_response:
        return {"response_format": {"type": "json_object"}}
    return {}
