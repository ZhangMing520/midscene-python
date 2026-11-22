"""Shared action/prompt helpers (upstream core/src/common.ts).

Python action schemas are plain dicts and DeviceAction carries precomputed
`locate_fields` / `distance_fields`, so the zod-based reflection in the
upstream module becomes simple field-list lookups here.
"""

import math
from typing import Any, Dict, List, Optional

from midscene.core.ai_model.shared.multimodal_prompt import user_prompt_to_string
from midscene.core.device import find_action_in_action_space_or_throw
from midscene.core.utils import format_timestamp

FINALIZE_ACTION_NAME = "Finalize"


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def user_prompt_to_multimodal_prompt(prompt: Any) -> Optional[Dict[str, Any]]:
    if isinstance(prompt, str) or not isinstance(prompt, dict):
        return None
    images = prompt.get("images")
    if not images:
        return None
    return {
        "images": images,
        "convertHttpImage2Base64": bool(prompt.get("convertHttpImage2Base64")),
    }


def if_midscene_locator_field(field: Any) -> bool:
    """Best-effort check for a `{ prompt }` locator schema field."""
    if isinstance(field, dict):
        properties = field.get("properties")
        if isinstance(properties, dict) and "prompt" in properties:
            return True
        return bool(field.get("locate"))
    return False


def find_all_midscene_locator_field(
    schema: Any, required_only: bool = False
) -> List[str]:
    """Return locator field names from a DeviceAction or schema mapping."""
    fields = _field(schema, "locate_fields")
    if isinstance(fields, list):
        if not required_only:
            return list(fields)
        param_schema = _field(schema, "param_schema")
        required: List[str] = []
        for name in fields:
            field = param_schema.get(name) if isinstance(param_schema, dict) else None
            if isinstance(field, dict) and field.get("optional") is True:
                continue
            required.append(name)
        return required
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return [
                name
                for name, field in properties.items()
                if if_midscene_locator_field(field)
            ]
    return []


def _screenshot_distances_to_logical(
    param: Dict[str, Any], schema: Any, ratio: float
) -> Dict[str, Any]:
    fields = list(_field(schema, "distance_fields") or [])
    if not fields:
        return param

    result = dict(param)
    for name in fields:
        value = param.get(name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite non-negative distance")
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("Invalid screenshot-to-logical coordinate ratio")
        result[name] = value / ratio
    return result


def _format_prompt_with_images(prompt_obj: Dict[str, Any]) -> str:
    prompt_string = str(prompt_obj.get("prompt", ""))
    images = prompt_obj.get("images")
    if isinstance(images, list) and images:
        count = len(images)
        prompt_string += f" (with {count} image{'s' if count > 1 else ''})"
    return prompt_string


def dump_action_param(
    json_object: Dict[str, Any], schema: Any
) -> Dict[str, Any]:
    """Flatten locator fields to strings for YAML output (upstream dumpActionParam)."""
    if not isinstance(json_object, dict):
        return {}

    locator_fields = find_all_midscene_locator_field(schema)
    result = dict(json_object)
    for field_name in locator_fields:
        field_value = result.get(field_name)
        if not field_value:
            continue
        if isinstance(field_value, str):
            continue
        if isinstance(field_value, dict):
            prompt = field_value.get("prompt")
            if isinstance(prompt, str):
                result[field_name] = prompt
            elif isinstance(prompt, dict) and prompt.get("prompt"):
                result[field_name] = _format_prompt_with_images(prompt)
    return result


def _param_field_schemas(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return properties
        return schema
    param_schema = getattr(schema, "param_schema", None)
    return param_schema if isinstance(param_schema, dict) else {}


def _apply_field_rules(name: str, field: Any, value: Any) -> Any:
    """Apply the schema field's refinement and transform, if any."""
    if not isinstance(field, dict):
        return value
    refine = field.get("refine")
    if callable(refine) and not refine(value):
        raise ValueError(f"{name}: Invalid value")
    transform = field.get("transform")
    if callable(transform):
        value = transform(value)
    return value


def parse_action_param(
    raw_param: Optional[Dict[str, Any]],
    schema: Any = None,
    options: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Validate/normalize action params (upstream parseActionParam).

    Locator fields are excluded from schema parsing and restored afterwards,
    mirroring upstream. Ordinary fields apply dict-descriptor refinements,
    transforms and defaults.
    """
    if schema is None:
        return None

    options = options or {}
    param = dict(raw_param or {})
    ratio = options.get("shrunkShotToLogicalRatio")
    if options.get("distanceUnit") == "model-input-image-pixel" and ratio is not None:
        param = _screenshot_distances_to_logical(param, schema, ratio)

    locate_fields = find_all_midscene_locator_field(schema)
    parsed = dict(param)
    for name, field in _param_field_schemas(schema).items():
        if name in locate_fields:
            continue
        if name in param:
            parsed[name] = _apply_field_rules(name, field, param[name])
        elif isinstance(field, dict) and "default" in field:
            parsed[name] = _apply_field_rules(
                name, field, field["default"]
            )

    if ratio is not None:
        for field_name in locate_fields:
            value = parsed.get(field_name)
            if isinstance(value, dict) and value.get("center"):
                center = value["center"]
                parsed[field_name] = {
                    **value,
                    "center": [
                        round(center[0] / ratio),
                        round(center[1] / ratio),
                    ],
                }
    return parsed


def validate_required_locate_fields(
    param: Optional[Dict[str, Any]], schema: Any
) -> None:
    for field in find_all_midscene_locator_field(schema, True):
        value = (param or {}).get(field)
        # Match JS truthiness: empty objects/arrays are truthy, unlike Python.
        present = bool(value) or isinstance(value, (dict, list))
        if not present:
            raise ValueError(f"{field}: Required locate field is not provided")


def _shortcut_field(action: Any) -> Optional[str]:
    name = _field(action, "name")
    alias = _field(action, "interface_alias")
    if name == "Launch" or alias == "launch":
        return "uri"
    if name == "Terminate" or alias == "terminate":
        return "uri"
    if (
        name == "RunAdbShell"
        or alias == "runAdbShell"
        or name == "RunHdcShell"
        or alias == "runHdcShell"
    ):
        return "command"
    return None


def build_yaml_flow_from_plans(
    plans: List[Dict[str, Any]],
    action_space: List[Any],
    shrunk_shot_to_logical_ratio: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Serialize planned actions as legacy YAML flow items."""
    flow: List[Dict[str, Any]] = []

    for plan in plans:
        verb = plan.get("type")
        action = find_action_in_action_space_or_throw(verb, action_space)
        flow_key = _field(action, "interface_alias") or verb

        if _field(action, "param_schema"):
            raw_param = plan.get("param") or {}
            if shrunk_shot_to_logical_ratio is not None:
                raw_param = _screenshot_distances_to_logical(
                    raw_param, action, shrunk_shot_to_logical_ratio
                )
            flow_param = dump_action_param(raw_param, action)
        else:
            flow_param = {}

        # Single-string params (Launch/Terminate `uri`, RunAdbShell `command`)
        # must be inlined on the flow key; otherwise the empty shorthand string
        # wins and cache replay calls the action with an empty argument.
        shortcut_field = _shortcut_field(action)
        can_inline = (
            shortcut_field is not None
            and list(flow_param.keys()) == [shortcut_field]
            and isinstance(flow_param[shortcut_field], str)
        )
        if can_inline:
            flow.append({flow_key: flow_param[shortcut_field]})
        else:
            flow.append({flow_key: "", **flow_param})

    return flow


def get_readable_time_string(
    format: str = "YYYY-MM-DD HH:mm:ss", timestamp: Optional[float] = None
) -> str:
    return format_timestamp(format, timestamp)


__all__ = [
    "FINALIZE_ACTION_NAME",
    "build_yaml_flow_from_plans",
    "dump_action_param",
    "find_action_in_action_space_or_throw",
    "find_all_midscene_locator_field",
    "get_readable_time_string",
    "if_midscene_locator_field",
    "parse_action_param",
    "user_prompt_to_multimodal_prompt",
    "user_prompt_to_string",
    "validate_required_locate_fields",
]
