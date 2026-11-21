"""Default planning protocol (upstream ai-model/model-adapter/default-planning-protocol.ts)."""

import json
from midscene.core.ai_model.shared.json import assert_json_object
from midscene.core.ai_model.shared.json import parse_model_response_json
from midscene.core.ai_model.shared.xml import extract_xml_tag
from midscene.core.ai_model.shared.model_locate_result import format_locate_example_value
from typing import Any, Dict, List, Optional

PLANNING_ACTION_OUTPUT_TAG_NAMES = ("action-type", "action-param-json")


PLANNING_ACTION_OUTPUT_RULES = "\n".join(
    [
        "- Use the <action-type> and <action-param-json> tags to output the action to be executed.",
        "- The value inside <action-type> MUST exactly match the 'type' field of one action in the Supporting actions list. 'complete' is NOT a valid action-type.",
        '- Parameter names are strict. Use EXACTLY the field names listed for the selected action. Do NOT invent alias fields. If the selected action provides a "sample" field, use the XML structure shown in that sample as the exact format for the action output.',
    ]
)


PLANNING_ACTION_OUTPUT_PLACEHOLDER = "\n".join(
    ["<action-type>...</action-type>", "<action-param-json>...</action-param-json>"]
)


def build_planning_action_output(build_input: Dict[str, Any]) -> str:
    """Serialize an action example into <action-type>/<action-param-json> XML."""
    action_name = build_input["actionName"]
    param = build_input.get("param") or {}
    locate_fields = build_input.get("locateFields")
    locate_result_key = build_input.get("locateResultKey")

    serialized_param: str
    if locate_fields and locate_result_key:
        serialized_param = _serialize_action_param(
            param, list(locate_fields), locate_result_key
        )
    else:
        serialized_param = json.dumps(param, indent=2, ensure_ascii=False)

    return (
        f"<action-type>{action_name}</action-type>\n"
        f"<action-param-json>\n{serialized_param}\n</action-param-json>"
    )


def _serialize_action_param(
    param: Dict[str, Any], locate_fields: List[str], locate_result_key: str
) -> str:
    """Serialize the param keeping locate result arrays on one line.

    Port of upstream serializeActionParam: values under locateResultKey inside
    locator objects are replaced with pre-formatted markers so JSON.stringify's
    indent does not split the coordinate array across lines.
    """
    locator_ids = set()
    for field in locate_fields:
        value = param.get(field)
        if isinstance(value, dict):
            locator_ids.add(id(value))

    marker_prefix = "__MIDSCENE_LOCATE_RESULT_EXAMPLE_"
    while marker_prefix in json.dumps(param, ensure_ascii=False):
        marker_prefix = f"_{marker_prefix}"

    replacements: Dict[str, str] = {}
    counter = {"n": 0}

    def replace(obj: Any, in_locator: bool) -> Any:
        if isinstance(obj, dict):
            is_locator = id(obj) in locator_ids
            out = {}
            for key, value in obj.items():
                if is_locator and key == locate_result_key:
                    marker = f"{marker_prefix}{counter['n']}__"
                    counter["n"] += 1
                    replacements[json.dumps(marker)] = format_locate_example_value(value)
                    out[key] = marker
                else:
                    out[key] = replace(value, in_locator=is_locator)
            return out
        if isinstance(obj, list):
            return [replace(item, in_locator) for item in obj]
        return obj

    transformed = replace(param, False)
    serialized = json.dumps(transformed, indent=2, ensure_ascii=False)
    for marker, locate_value in replacements.items():
        serialized = serialized.replace(marker, locate_value)
    return serialized


def create_planning_action_output_parser():
    """Parse <action-type>/<action-param-json> content into an action dict."""

    def parse_action_output(content: str, action_space: List[Any]) -> Optional[Dict[str, Any]]:
        action_type = extract_xml_tag(content, "action-type")
        action_param_str = extract_xml_tag(content, "action-param-json")

        if not action_type or action_type.lower() == "null":
            return None

        # Strip any trailing XML tags that leaked into the action type.
        action_type = action_type.split("<")[0].strip()
        param: Optional[Dict[str, Any]] = None

        if action_param_str:
            try:
                param = parse_model_response_json(
                    action_param_str,
                    source="planning-action-param",
                    preserve_string_value_keys=(
                        ["value"] if action_type.lower() == "input" else None
                    ),
                )
                assert_json_object(param)
            except Exception as error:
                raise ValueError(f"Failed to parse action-param-json: {error}")

        result: Dict[str, Any] = {"type": action_type}
        if param is not None:
            result["param"] = param
        return result

    return parse_action_output


def build_locate_field_description(
    locate_prompt_spec: Optional[Dict[str, Any]] = None,
) -> str:
    if locate_prompt_spec:
        return (
            "{ prompt: string, "
            f"{locate_prompt_spec['resultKey']}: {locate_prompt_spec['resultValueSchema']}"
            f" /* {locate_prompt_spec['resultValueDescription']} */ }}"
        )
    return "{ prompt: string /* description of the target element */ }"


def _default_build_action_description(build_input: Dict[str, Any]) -> Dict[str, Any]:
    """Build one YAML action description from a DeviceAction prompt dict."""
    action = build_input["action"]
    action_dict = action if isinstance(action, dict) else action.to_prompt_dict()
    locate_field_description = build_input["locate_field_description"]

    description: Dict[str, Any] = {
        "type": action_dict["name"],
        "description": action_dict.get("description") or "No description provided",
    }

    param_schema = action_dict.get("param_schema")
    if param_schema:
        param: Dict[str, Any] = {}
        locate_fields = list(action_dict.get("locate_fields", []))
        distance_fields = list(action_dict.get("distance_fields", []))
        for key, field in param_schema.items():
            field = dict(field)
            if key in locate_fields:
                field["type"] = locate_field_description
            if key in distance_fields:
                unit = (
                    "Use pixels of the input image for this distance, even "
                    "when position coordinates are normalized."
                )
                field_description = field.get("description")
                field["description"] = (
                    f"{unit} {field_description}" if field_description else unit
                )
            param[key] = field
        if param:
            description["param"] = param

    if build_input.get("action_output_example"):
        description["sample"] = build_input["action_output_example"]

    return description


def create_default_planning_protocol() -> Dict[str, Any]:
    """The default Midscene XML planning protocol (StandardPlanningProtocol)."""
    return {
        "response_prefix": None,
        "action_space_protocol": {
            "title": "Supporting actions list",
            "format": "yaml",
            "include_action_output_example": True,
            "build_locate_field_description": build_locate_field_description,
            "build_action_description": _default_build_action_description,
        },
        "action_output_protocol": {
            "action_output_tag_names": PLANNING_ACTION_OUTPUT_TAG_NAMES,
            "action_output_rules": PLANNING_ACTION_OUTPUT_RULES,
            "action_output_placeholder": PLANNING_ACTION_OUTPUT_PLACEHOLDER,
            "build_action_output": build_planning_action_output,
            "parse_action_output": create_planning_action_output_parser(),
            # Planning locate parameters pass through unchanged; normalization
            # happens in the planning workflow (parsePlanningActions).
            "parse_raw_locate_parameter": lambda value: value,
        },
    }
