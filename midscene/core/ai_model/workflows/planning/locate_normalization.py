"""Planning locate parameter normalization (upstream workflows/planning/locate-normalization.ts)."""

from typing import Any, Dict, Optional


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


__all__ = ["normalize_planning_locate_parameter"]
