"""Default Responses API params (upstream model-adapter/responses.ts)."""

from typing import Any, Dict

MIDSCENE_RESPONSES_DEFAULTS: Dict[str, Any] = {"temperature": 0.0}


def build_default_responses_params(
    midscene_defaults: Dict[str, Any],
    user_config: Dict[str, Any],
    expected_json_object_response: bool = False,
) -> Dict[str, Any]:
    """Default `buildResponsesParams` used when an adapter has no override."""
    return {
        **midscene_defaults,
        **{
            key: value
            for key, value in user_config.items()
            if value is not None and value != "unset"
        },
    }


__all__ = ["MIDSCENE_RESPONSES_DEFAULTS", "build_default_responses_params"]
