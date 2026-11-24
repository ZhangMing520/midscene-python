"""Default locate / search-area protocols (upstream ai-model/model-adapter/default-locate-protocol.ts)."""

from typing import Any

from midscene.core.ai_model.model_adapter.locate_protocol import (
    ParsedLocateResponse,
    StandardLocateProtocol,
)
from midscene.core.ai_model.shared.json import (
    assert_json_object,
    parse_model_response_json,
)
from midscene.core.ai_model.shared.model_locate_result import (
    format_locate_example_value,
    read_locate_result_field,
)

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


def _build_locate_response_instructions(prompt_spec: dict[str, Any]) -> str:
    preferred_language = "English"
    from midscene.shared.env import get_preferred_language

    preferred_language = get_preferred_language()
    result_key = prompt_spec["resultKey"]
    example_value_text = format_locate_example_value(prompt_spec["exampleValues"][0])
    result_field_description = f"the {prompt_spec['resultNoun']} of the element that matches the user's description"
    return f"""## Output Format:
```json
{{
  "{result_key}": {prompt_spec["resultValueSchema"]},  // {prompt_spec["resultValueDescription"]}
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


def _build_search_area_response_instructions(prompt_spec: dict[str, Any]) -> str:
    from midscene.shared.env import get_preferred_language

    preferred_language = get_preferred_language()
    result_key = prompt_spec["resultKey"]
    example_value_text = format_locate_example_value(prompt_spec["exampleValues"][0])
    result_json_property = (
        f'"{result_key}": {prompt_spec["resultValueSchema"]},  // '
        f"{prompt_spec['resultValueDescription']}"
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
    {prompt_spec["resultValueSchema"]},
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


def _create_parse_raw_response(
    json_source: str,
    include_references: bool,
    json_parser=None,
):
    def parse_raw_response(
        content: str, prompt_spec: dict[str, Any]
    ) -> ParsedLocateResponse:
        parser = json_parser or (
            lambda raw, source: parse_model_response_json(raw, source=source)
        )
        parsed_response = parser(content, json_source)
        assert_json_object(parsed_response)
        record: dict[str, Any] = parsed_response
        target = read_locate_result_field(record, prompt_spec)
        error = record["error"] if isinstance(record.get("error"), str) else None
        if target is None:
            raise ValueError(
                f'Missing required coordinate field "{prompt_spec["resultKey"]}". '
                f'Expected "{prompt_spec["resultKey"]}": '
                f"{prompt_spec.get('resultValueSchema', '[number, number, number, number]')}; "
                "use an empty array when no element is found."
                + (f" Model error: {error}" if error else "")
            )
        if isinstance(target, list) and len(target) == 0:
            result: dict[str, Any] = {"kind": "not-found"}
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
                raw_references if isinstance(raw_references, list) else [raw_references]
            )
        result = {"kind": "located", "target": target}
        if references:
            result["references"] = references
        if error:
            result["error"] = error
        return result

    return parse_raw_response


def create_default_element_protocol(json_parser=None) -> StandardLocateProtocol:
    return {
        "system_prompt_introduction": DEFAULT_LOCATE_SYSTEM_PROMPT_INTRODUCTION,
        "build_response_instructions": _build_locate_response_instructions,
        "build_user_prompt": _build_locate_user_prompt,
        "expected_json_object_response": True,
        "parse_raw_response": _create_parse_raw_response("locate", False, json_parser),
    }


def create_default_search_area_protocol(json_parser=None) -> StandardLocateProtocol:
    return {
        "system_prompt_introduction": DEFAULT_SEARCH_AREA_SYSTEM_PROMPT_INTRODUCTION,
        "build_response_instructions": _build_search_area_response_instructions,
        "build_user_prompt": _build_search_area_user_prompt,
        "expected_json_object_response": True,
        "parse_raw_response": _create_parse_raw_response(
            "section-locator", True, json_parser
        ),
    }
