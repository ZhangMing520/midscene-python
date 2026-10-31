"""Default model protocols: planning (Midscene XML), locate (JSON), insight (data-json).

Synced from upstream packages/core/src/ai-model/model-adapter/:
  default-planning-protocol.ts, default-locate-protocol.ts,
  default-insight-protocol.ts
"""

import json
from typing import Any, Dict, List, Optional

from .json_utils import assert_json_object, parse_model_response_json
from .locate_result import format_locate_example_value, read_locate_result_field
from .xml_utils import extract_xml_tag

# ---------------------------------------------------------------------------
# Planning protocol (default-planning-protocol.ts)
# ---------------------------------------------------------------------------

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
        for key, field in param_schema.items():
            field = dict(field)
            if key in locate_fields:
                field["type"] = locate_field_description
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


# ---------------------------------------------------------------------------
# Locate protocols (default-locate-protocol.ts)
# ---------------------------------------------------------------------------

DEFAULT_LOCATE_SYSTEM_PROMPT_INTRODUCTION = """## Role:
You are an AI assistant that helps identify UI elements.

## Objective:
- Identify elements in screenshots that match the user's description.
- Provide the coordinates of the element that matches the user's description."""

DEFAULT_SEARCH_AREA_SYSTEM_PROMPT_INTRODUCTION = """## Role:
You are an AI assistant that helps identify UI elements.

## Objective:
- Find a section containing the target element
- If the description mentions reference elements, also locate sections containing those references"""


def _build_locate_response_instructions(prompt_spec: Dict[str, Any]) -> str:
    preferred_language = "English"
    from .env_config import get_preferred_language

    preferred_language = get_preferred_language()
    result_key = prompt_spec["resultKey"]
    example_value_text = format_locate_example_value(prompt_spec["exampleValues"][0])
    result_field_description = (
        f"the {prompt_spec['resultNoun']} of the element that matches the user's description"
    )
    return f"""## Output Format:
```json
{{
  "{result_key}": {prompt_spec['resultValueSchema']},  // {prompt_spec['resultValueDescription']}
  "error": string // optional
}}
```

Fields:
* `{result_key}` is {result_field_description}
* `error` is an optional error message (if any)

For example, when an element is found:
```json
{{
  "{result_key}": {example_value_text}
}}
```

When no element is found:
```json
{{
  "{result_key}": [],
  "error": "I can see ..., but {{some element}} is not found. Use {preferred_language}."
}}
```
"""


def _build_locate_user_prompt(target_element_description: str) -> str:
    return f"Find: {target_element_description}"


def _build_search_area_response_instructions(prompt_spec: Dict[str, Any]) -> str:
    from .env_config import get_preferred_language

    preferred_language = get_preferred_language()
    result_key = prompt_spec["resultKey"]
    example_value_text = format_locate_example_value(prompt_spec["exampleValues"][0])
    result_json_property = (
        f'"{result_key}": {prompt_spec["resultValueSchema"]},  // '
        f'{prompt_spec["resultValueDescription"]}'
    )
    result_field_description = (
        f"{prompt_spec['resultNoun']} of the section containing the target element"
    )
    reference_field_description = (
        f"Optional array of {prompt_spec['resultNounPlural']} of reference elements"
    )
    return f"""## Output Format:
```json
{{
  {result_json_property}
  "references_{result_key}"?: [
    {prompt_spec['resultValueSchema']},
    ...
  ],
  "error"?: string
}}
```

Fields:
* `{result_key}` - {result_field_description}
* `references_{result_key}` - {reference_field_description}
* `error` - Optional error message if the section cannot be found. Use {preferred_language}.

Example:
If the description is "delete button on the second row with title 'Peter'", return:
```json
{{
  "{result_key}": {example_value_text},
  "references_{result_key}": [{example_value_text}]
}}
```
"""


def _build_search_area_user_prompt(section_description: str) -> str:
    return f"Find section containing: {section_description}"


def _create_parse_raw_response(json_source: str, include_references: bool):
    def parse_raw_response(
        content: str, prompt_spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        parsed_response = parse_model_response_json(content, source=json_source)
        assert_json_object(parsed_response)
        record: Dict[str, Any] = parsed_response
        target = read_locate_result_field(record, prompt_spec)
        error = (
            record["error"] if isinstance(record.get("error"), str) else None
        )
        if target is None:
            raise ValueError(
                f'Missing required coordinate field "{prompt_spec["resultKey"]}". '
                f'Expected "{prompt_spec["resultKey"]}": '
                f'{prompt_spec.get("resultValueSchema", "[number, number, number, number]")}; '
                "use an empty array when no element is found."
                + (f" Model error: {error}" if error else "")
            )
        if isinstance(target, list) and len(target) == 0:
            result: Dict[str, Any] = {"kind": "not-found"}
            if error:
                result["error"] = error
            return result

        if not include_references:
            result = {"kind": "located", "target": target}
            if error:
                result["error"] = error
            return result

        raw_references = read_locate_result_field(record, prompt_spec, "references_")
        references = None
        if raw_references is not None:
            references = (
                raw_references
                if isinstance(raw_references, list)
                else [raw_references]
            )
        result = {"kind": "located", "target": target}
        if references:
            result["references"] = references
        if error:
            result["error"] = error
        return result

    return parse_raw_response


def create_default_element_protocol() -> Dict[str, Any]:
    return {
        "system_prompt_introduction": DEFAULT_LOCATE_SYSTEM_PROMPT_INTRODUCTION,
        "build_response_instructions": _build_locate_response_instructions,
        "build_user_prompt": _build_locate_user_prompt,
        "expected_json_object_response": True,
        "parse_raw_response": _create_parse_raw_response("locate", False),
    }


def create_default_search_area_protocol() -> Dict[str, Any]:
    return {
        "system_prompt_introduction": DEFAULT_SEARCH_AREA_SYSTEM_PROMPT_INTRODUCTION,
        "build_response_instructions": _build_search_area_response_instructions,
        "build_user_prompt": _build_search_area_user_prompt,
        "expected_json_object_response": True,
        "parse_raw_response": _create_parse_raw_response("section-locator", True),
    }


# ---------------------------------------------------------------------------
# Insight protocol (default-insight-protocol.ts)
# ---------------------------------------------------------------------------

INSIGHT_DATA_OUTPUT_TAG_NAME = "data-json"


def create_default_insight_protocol() -> Dict[str, Any]:
    tag = INSIGHT_DATA_OUTPUT_TAG_NAME

    def parse_data(content: str) -> Any:
        data_json_content = extract_xml_tag(content, tag)
        if not data_json_content:
            raise ValueError("Missing required field: data-json")
        try:
            return parse_model_response_json(data_json_content, source="generic-object")
        except Exception as error:
            raise ValueError(f"Failed to parse data-json: {error}")

    return {
        "response_prefix": None,
        "data_output": {
            "tag_names": (tag,),
            "rules": "",
            "placeholder": (
                f"<{tag}>the extracted data as JSON. Make sure both the value and "
                "scheme meet the DATA_DEMAND. If you want to write some description "
                f"in this field, use the same language as the DATA_DEMAND.</{tag}>"
            ),
            "build_example": lambda serialized_data: (
                f"<{tag}>\n{serialized_data}\n</{tag}>"
            ),
            "parse": parse_data,
        },
    }
