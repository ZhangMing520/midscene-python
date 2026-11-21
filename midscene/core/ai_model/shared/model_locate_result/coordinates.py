"""Coordinate system resolution (upstream shared/model-locate-result/coordinates.ts)."""

from typing import Any, Dict, Optional

from midscene.core.ai_model.shared.model_locate_result.types import (
    BboxBoundsType,
    NormalizationBasis,
)

BOUNDS_TYPE_ALIASES = {
    "closed": "closed",
    "inclusive": "closed",
    "left-closed-right-open": "left-closed-right-open",
    "edges": "left-closed-right-open",
}
NORMALIZATION_BASES = ("image-size", "last-pixel")


def resolve_bounds_type(value: Optional[str]) -> BboxBoundsType:
    if value is None:
        return "closed"
    canonical = BOUNDS_TYPE_ALIASES.get(value)
    if canonical is None:
        raise ValueError(f"invalid locate bbox boundsType: {value}")
    return canonical


def resolve_normalization_basis(value: Optional[str]) -> NormalizationBasis:
    basis = value or "image-size"
    if basis not in NORMALIZATION_BASES:
        raise ValueError(f"invalid normalization basis: {basis}")
    return basis


def resolve_locate_result_coordinates(coordinates: Dict[str, Any]) -> Dict[str, Any]:
    normalized_by = coordinates.get("normalizedBy")
    if normalized_by is not None and normalized_by <= 0:
        raise ValueError(
            f"locate result coordinates normalizedBy must be positive: {normalized_by}"
        )
    resolved: Dict[str, Any] = {
        "shape": coordinates["shape"],
        "order": coordinates.get("order") or "xy",
        "normalizedBy": normalized_by,
        "normalizationBasis": resolve_normalization_basis(
            coordinates.get("normalizationBasis")
        ),
        "rounding": coordinates.get("rounding") or "round",
    }
    if coordinates["shape"] == "bbox":
        resolved["boundsType"] = resolve_bounds_type(
            coordinates.get("boundsType")
        )
    return resolved
