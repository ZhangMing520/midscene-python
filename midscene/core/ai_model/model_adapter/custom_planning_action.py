"""Custom planning action helpers (upstream model-adapter/custom-planning-action.ts)."""

from typing import Any

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_codec,
    resolve_locate_result_coordinates,
)


def normalize_custom_locate_fields(
    actions: list[dict[str, Any]],
    coordinates: dict[str, Any],
    locate_result_context: dict[str, Any],
) -> None:
    """Convert raw `point`/`bbox` coordinates on locate params into
    `locatedPixelResult` (upstream normalizePlanningActionLocateFields)."""
    if not coordinates:
        return
    resolved = resolve_locate_result_coordinates(coordinates)
    codec = create_locate_result_codec({"coordinates": resolved})
    result_key = codec.prompt_spec["resultKey"]

    for action in actions:
        param = action.get("param") or {}
        for field, value in list(param.items()):
            if not isinstance(value, dict) or "prompt" not in value:
                continue
            raw = value.get(result_key)
            if raw is None:
                continue
            pixel_result = codec.to_pixel_result(raw, locate_result_context)
            rest = {k: v for k, v in value.items() if k != result_key}
            param[field] = {**rest, "locatedPixelResult": pixel_result}


def get_tap_located_pixel_result(
    actions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """First Tap action's locatedPixelResult (custom-planning-action.ts)."""
    for action in actions:
        if action.get("type") != "Tap":
            continue
        locate = (action.get("param") or {}).get("locate") or {}
        return locate.get("locatedPixelResult")
    return None


# Backward-compatible private alias used by the custom planning workflow.
_normalize_custom_locate_fields = normalize_custom_locate_fields


__all__ = [
    "get_tap_located_pixel_result",
    "normalize_custom_locate_fields",
]
