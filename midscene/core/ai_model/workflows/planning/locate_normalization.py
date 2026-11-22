"""Planning locate parameter normalization (upstream workflows/planning/locate-normalization.ts)."""

from typing import Any, Dict, List, Optional


def normalize_planning_locate_parameter(
    locate: Dict[str, Any],
    locate_result_codec: Optional[Any],
    locate_result_context: Optional[Dict[str, Any]],
    include_locate_in_planning: bool,
) -> Dict[str, Any]:
    """Normalize a planning locate parameter into {prompt, ...}.

    When the planning model returned coordinates (includeLocateInPlanning) they
    are mapped to pixels and attached as `locatedPixelResult`; otherwise the
    parameter keeps only the prompt and locate runs at execution time.
    """
    prompt = locate.get("prompt")
    if not include_locate_in_planning:
        return {"prompt": prompt}

    if locate_result_codec is None:
        raise ValueError(
            "planning locate normalization requires a locate result codec"
        )

    spec = locate_result_codec.prompt_spec
    raw_keys = [spec["resultKey"], *(spec.get("resultKeyAliases") or [])]
    raw_value = next(
        (locate[key] for key in raw_keys if key in locate), None
    )
    # Drop raw coordinate fields after converting them.
    normalized = {key: value for key, value in locate.items() if key not in raw_keys}
    normalized["locatedPixelResult"] = locate_result_codec.to_pixel_result(
        raw_value, locate_result_context or {}
    )
    return normalized


def _action_locate_fields(action_definition: Any) -> list:
    action_dict = (
        action_definition
        if isinstance(action_definition, dict)
        else action_definition.to_prompt_dict()
    )
    return list(action_dict.get("locate_fields", []))


def normalize_planning_action_fields(
    actions: List[Dict[str, Any]],
    action_space: List[Any],
    include_locate_in_planning: bool,
    locate_result_codec: Optional[Any],
    locate_result_context: Optional[Dict[str, Any]],
) -> None:
    """Normalize locate params on planned actions in place.

    Mirrors upstream ``normalizePlanningActionFields``: actions outside the
    action space are skipped, and only fields declared as Midscene locators
    are converted.
    """
    for action in actions:
        action_in_space = next(
            (
                candidate
                for candidate in action_space
                if (
                    candidate.get("name")
                    if isinstance(candidate, dict)
                    else getattr(candidate, "name", None)
                )
                == action.get("type")
            ),
            None,
        )
        if action_in_space is None:
            continue

        param = action.get("param") or {}
        for field in _action_locate_fields(action_in_space):
            locate_parameter = param.get(field)
            if not locate_parameter:
                continue
            param[field] = normalize_planning_locate_parameter(
                locate_parameter,
                locate_result_codec,
                locate_result_context,
                include_locate_in_planning,
            )


__all__ = [
    "normalize_planning_action_fields",
    "normalize_planning_locate_parameter",
]
