"""Decode raw CLI tokens against a tool schema (upstream cli/cli-value.ts).

Upstream schemas are Zod objects; the Python port uses plain dict field
descriptors (``{"type": "string", "optional": True, ...}``) because the
runtime does not depend on Zod. Only the value-shape semantics are ported.
"""

import json
import re
from typing import Any, Dict, List, Optional

_CLI_NUMBER_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")

Field = Dict[str, Any]


def _parse_json_value(raw: str) -> Any:
    if not raw.startswith("{") and not raw.startswith("["):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        # Preserve text for string inputs or the later schema validation error.
        return raw


def parse_value(raw: str) -> Any:
    parsed = _parse_json_value(raw)
    if parsed != raw:
        return parsed
    if _CLI_NUMBER_PATTERN.match(raw):
        return float(raw) if "." in raw else int(raw)
    return raw


def _type_names(field: Field) -> List[str]:
    raw = field.get("type", "any")
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw]
    return [part.strip() for part in str(raw).split("|")]


def _union_options(field: Field) -> Optional[List[Field]]:
    """Return the structured alternatives of a union descriptor."""
    options = field.get("options")
    if not isinstance(options, (list, tuple)):
        return None
    alternatives = [option for option in options if isinstance(option, dict)]
    return alternatives or None


def _accepts_type(type_name: str, field: Field, value: Any) -> Optional[bool]:
    name = type_name.strip().lower()
    if name.endswith("[]"):
        if not isinstance(value, list):
            return False
        inner = dict(field)
        inner["type"] = name[:-2]
        return all(_accepts_value(inner, item) is not False for item in value)

    if name in ("string", "str"):
        return isinstance(value, str)
    if name in ("number", "float"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name in ("integer", "int"):
        return isinstance(value, int) and not isinstance(value, bool)
    if name in ("boolean", "bool"):
        return isinstance(value, bool)
    if name == "locate":
        return isinstance(value, (str, dict))
    if name in ("array", "list", "tuple"):
        return isinstance(value, list)
    if name in ("object", "record", "dict"):
        return isinstance(value, dict)
    if name in ("null", "none"):
        return value is None
    if name == "literal":
        return value == field.get("value")
    if name == "enum":
        return value in (field.get("enum") or [])
    if name == "nativeenum":
        values = field.get("enum", field.get("values"))
        if isinstance(values, dict):
            values = list(values.values())
        return value in (values or [])
    if name in ("any", "unknown"):
        return None
    return None


def _accepts_value(field: Field, value: Any) -> Optional[bool]:
    """Only inspect scalar constraints; collections keep full validation."""
    options = _union_options(field)
    if options is not None:
        unknown = False
        for option in options:
            result = _accepts_value(option, value)
            if result is True:
                return True
            if result is None:
                unknown = True
        return None if unknown else False

    unknown = False
    for type_name in _type_names(field):
        result = _accepts_type(type_name, field, value)
        if result is True:
            return True
        if result is None:
            unknown = True
    return None if unknown else False


def _uses_legacy_inference(field: Field) -> bool:
    return any(name.lower() in ("any", "unknown") for name in _type_names(field))


def _get_input_fields(field: Field) -> List[Field]:
    # Keep the actual alternatives: a string literal is not an arbitrary
    # string, and a repeated tuple argument must retain its position-specific
    # schema.
    options = _union_options(field)
    if options is None:
        return [field]
    flattened: List[Field] = []
    for option in options:
        flattened.extend(_get_input_fields(option))
    return flattened


def _collection_kind(field: Field) -> Optional[str]:
    for name in _type_names(field):
        lowered = name.lower()
        if lowered == "tuple":
            return "tuple"
        if lowered in ("array", "list") or lowered.endswith("[]"):
            return "array"
    return None


def _get_repeated_input_fields(fields: List[Field], index: int) -> List[Field]:
    collections = [
        (field, kind)
        for field in fields
        if (kind := _collection_kind(field)) is not None
    ]
    if not collections:
        return fields
    repeated: List[Field] = []
    for field, kind in collections:
        if kind == "tuple":
            items = field.get("items")
            item: Any = None
            if isinstance(items, (list, tuple)) and index < len(items):
                item = items[index]
            if item is None:
                item = field.get("rest")
            if isinstance(item, dict):
                repeated.extend(_get_input_fields(item))
            continue
        item = field.get("items")
        if isinstance(item, dict):
            repeated.extend(_get_input_fields(item))
            continue
        for name in _type_names(field):
            lowered = name.lower()
            if lowered.endswith("[]"):
                repeated.append(
                    {
                        "type": name[:-2],
                        "description": field.get("description", ""),
                    }
                )
            elif lowered in ("array", "list"):
                repeated.append({"type": "any"})
    return repeated or fields


def parse_cli_value(
    raw: str, field: Optional[Field] = None, index: Optional[int] = None
) -> Any:
    """Decode one CLI token; index is supplied only for repeated options."""
    if not field:
        return parse_value(raw)
    parsed_json = _parse_json_value(raw)
    whole_fields = _get_input_fields(field)
    if parsed_json != raw and any(
        _accepts_value(input_field, parsed_json) is True
        for input_field in whole_fields
    ):
        return parsed_json

    fields = (
        whole_fields
        if index is None
        else _get_repeated_input_fields(whole_fields, index)
    )
    candidates: List[Any] = [parsed_json, raw] if parsed_json != raw else [raw]
    if _CLI_NUMBER_PATTERN.match(raw):
        candidates.append(int(raw) if "." not in raw else float(raw))
    if raw in ("true", "false"):
        candidates.append(raw == "true")
    for candidate in candidates:
        if any(_accepts_value(input_field, candidate) is True for input_field in fields):
            return candidate
    if any(_uses_legacy_inference(input_field) for input_field in fields):
        return parse_value(raw)
    return raw


__all__ = ["parse_cli_value", "parse_value"]
