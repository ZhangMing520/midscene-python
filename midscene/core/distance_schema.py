"""Distance field metadata (upstream packages/core/src/distance-schema.ts).

Python action schemas declare distance fields explicitly, so the zod
reflection in the upstream module becomes a simple field list lookup.
"""

from typing import Any, List, Optional

DISTANCE_UNITS = ("model-input-image-pixel", "device-logical")


def is_distance_field(field: Any) -> bool:
    """Whether a schema field is marked as a distance."""
    if isinstance(field, dict):
        return bool(field.get("midsceneDistance") or field.get("distance"))
    return bool(getattr(field, "distance", False))


def find_distance_fields(schema: Optional[Any] = None) -> List[str]:
    """Return the distance field names of an action schema."""
    if schema is None:
        return []

    declared = getattr(schema, "distance_fields", None)
    if isinstance(declared, (list, tuple)):
        return list(declared)
    if isinstance(schema, dict):
        declared = schema.get("distance_fields")
        if isinstance(declared, (list, tuple)):
            return list(declared)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return [
                name
                for name, field in properties.items()
                if is_distance_field(field)
            ]
    return []


__all__ = ["DISTANCE_UNITS", "find_distance_fields", "is_distance_field"]
