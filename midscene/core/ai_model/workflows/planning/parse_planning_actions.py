"""Planning action validation/normalization (upstream workflows/planning/parse-planning-actions.ts)."""

from typing import Any, Dict, List, Optional

from midscene.core.ai_model.workflows.planning.locate_normalization import (
    normalize_planning_locate_parameter,
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
    from midscene.core.device import find_action_in_action_space_or_throw

    for action in actions:
        definition = find_action_in_action_space_or_throw(action["type"], action_space)
        locate_fields = list(definition.locate_fields) if not isinstance(definition, dict) else list(
            definition.get("locate_fields", [])
        )
        try:
            param = action.get("param")
            if param is None:
                param = {}
                action["param"] = param

            for field in locate_fields:
                raw_locate = param.get(field)
                if raw_locate is not None:
                    param[field] = parse_raw_locate_parameter(raw_locate)

            for field in locate_fields:
                locate = param.get(field)
                if locate is None:
                    continue
                if not isinstance(locate, dict):
                    raise ValueError(f"{field}: Expected an object with a prompt field")
                if locate.get("prompt") is None:
                    raise ValueError(f"{field}.prompt: Required")
                if not isinstance(locate["prompt"], str) and not isinstance(
                    locate["prompt"], dict
                ):
                    raise ValueError(
                        f"{field}.prompt: Expected a string or an object with a prompt field"
                    )
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
