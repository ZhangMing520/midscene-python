"""Default model parameters and locate format (upstream ai-model/models/default.ts)."""

from typing import Any, Dict

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    _apply_temperature,
)
from midscene.core.ai_model.model_adapter.types import (
    ModelRequestUserConfig,
)

def _build_default_params(
    midscene_defaults: Dict[str, Any],
    user_config: ModelRequestUserConfig,
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(midscene_defaults)
    return _apply_temperature(config, user_config)


DEFAULT_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": {
        "shape": "bbox",
        "order": "xy",
        "normalizedBy": 1000,
        "rounding": "round",
    },
}
