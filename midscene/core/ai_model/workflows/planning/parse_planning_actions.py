"""Planning action validation/normalization (upstream workflows/planning/parse-planning-actions.ts)."""

from typing import Any, Dict, List, Optional

from midscene.core.ai_model.workflows.planning.locate_normalization import (
    normalize_planning_locate_parameter,
)


def _param_schema_of(definition: Any) -> Optional[Dict[str, Any]]:
    if isinstance(definition, dict):
        return definition.get("param_schema")
    return getattr(definition, "param_schema", None)


def _validate_user_prompt(prompt: Any, field: str) -> None:
    """Validate the model-facing prompt (upstream TUserPromptSchema)."""
    if isinstance(prompt, str):
        return
    if isinstance(prompt, dict):
        inner_prompt = prompt.get("prompt")
        if isinstance(inner_prompt, str):
            return
        if inner_prompt is None:
            raise ValueError(f"{field}.prompt: Required")
        raise ValueError(
            f"{field}.prompt: Expected a string or an object with a prompt field"
        )
    raise ValueError(
        f"{field}.prompt: Expected a string or an object with a prompt field"
    )


def parse_planning_actions(
    actions: List[Dict[str, Any]],
    action_space: List[Any],
    parse_raw_locate_parameter,
    include_locate_in_planning: bool,
    locate_result_codec: Optional[Any] = None,
    locate_result_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Validate and normalize planning actions in place."""
    from midscene.core.common import (
        find_all_midscene_locator_field,
        parse_action_param,
        validate_required_locate_fields,
    )
    from midscene.core.device import find_action_in_action_space_or_throw

    for action in actions:
        definition = find_action_in_action_space_or_throw(
            action["type"], action_space
        )
        if not _param_schema_of(definition):
            continue

        locate_fields = find_all_midscene_locator_field(definition)
        try:
            param = action.get("param")
            for field in locate_fields:
                if not isinstance(param, dict) or field not in param:
                    continue
                raw_locate = param[field]
                if raw_locate is not None:
                    param[field] = parse_raw_locate_parameter(raw_locate)

            validate_required_locate_fields(param, definition)
            # Preflight validation only: ordinary parameters stay unchanged.
            parse_action_param(param, definition)

            for field in locate_fields:
                if not isinstance(param, dict) or field not in param:
                    continue
                locate = param[field]
                # Validate only the model-facing prompt; coordinates are
                # normalized later at execution time.
                if not isinstance(locate, dict):
                    raise ValueError(
                        f"{field}: Expected an object with a prompt field"
                    )
                if "prompt" not in locate:
                    raise ValueError(f"{field}.prompt: Required")
                _validate_user_prompt(locate["prompt"], field)
                param[field] = normalize_planning_locate_parameter(
                    locate,
                    locate_result_codec,
                    locate_result_context,
                    include_locate_in_planning,
                )
        except Exception as error:
            raise ValueError(
                f"Invalid parameters for action {action['type']}: {error}"
            ) from error


__all__ = ["parse_planning_actions"]
