"""Default Responses API params (upstream model-adapter/responses.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.model_adapter.temperature_with_semantic_retry import (
    get_temperature_with_semantic_retry,
)

MIDSCENE_RESPONSES_DEFAULTS: Dict[str, Any] = {"temperature": 0}


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


def _default_responses_params(context: Dict[str, Any]) -> Dict[str, Any]:
    user_config = context.get("userConfig") or {}
    defaults = context.get("midsceneDefaults") or MIDSCENE_RESPONSES_DEFAULTS
    return {
        "config": {
            "temperature": user_config.get("temperature", defaults.get("temperature"))
        }
    }


def resolve_responses(
    responses: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve a Responses definition into a runtime adapter."""
    responses = responses or {}
    build_params = responses.get("build_responses_params") or _default_responses_params
    replay_raw_assistant_output = bool(
        responses.get("replay_raw_assistant_output", False)
    )

    def build_responses_params(input_context: Dict[str, Any]) -> Dict[str, Any]:
        context = {
            **input_context,
            "userConfig": input_context.get("userConfig") or {},
            "midsceneDefaults": MIDSCENE_RESPONSES_DEFAULTS,
        }
        params = build_params(context)
        return {
            **params,
            "config": {
                **(params.get("config") or {}),
                "temperature": get_temperature_with_semantic_retry(
                    (params.get("config") or {}).get("temperature"),
                    (input_context.get("userConfig") or {}).get("temperature"),
                    input_context.get("semanticRetryAttempt") or 0,
                ),
            },
        }

    return {
        "replay_raw_assistant_output": replay_raw_assistant_output,
        "build_responses_params": build_responses_params,
    }


__all__ = [
    "MIDSCENE_RESPONSES_DEFAULTS",
    "build_default_responses_params",
    "resolve_responses",
]
