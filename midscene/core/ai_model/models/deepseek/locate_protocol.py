"""DeepSeek locate protocol (upstream ai-model/models/deepseek/locate-protocol.ts)."""

from typing import Any

from midscene.core.ai_model.shared.model_locate_result import (
    create_locate_result_value,
)

DEEPSEEK_POINT_COORDS = {
    "shape": "point",
    "order": "xy",
    "normalizedBy": 1000,
    "rounding": "round",
}


DEEPSEEK_BBOX_COORDS = {
    "shape": "bbox",
    "order": "xy",
    "normalizedBy": 1000,
    "rounding": "round",
}


def _parse_deepseek_coordinate_values(
    input_value: Any, expected_length: int, label: str
) -> list[int]:
    import re as _re

    coordinate_texts = _re.findall(r"\d+", str(input_value))
    if len(coordinate_texts) != expected_length:
        raise ValueError(
            f"DeepSeek {label} locate result must contain exactly "
            f"{expected_length} positive integers, got {len(coordinate_texts)}"
        )
    return [int(t) for t in coordinate_texts]


def _parse_deepseek_point_locate_value(input_value: Any) -> dict[str, Any]:
    return create_locate_result_value(
        DEEPSEEK_POINT_COORDS,
        _parse_deepseek_coordinate_values(input_value, 2, "point"),
    )


def _parse_deepseek_bbox_locate_value(input_value: Any) -> dict[str, Any]:
    return create_locate_result_value(
        DEEPSEEK_BBOX_COORDS,
        _parse_deepseek_coordinate_values(input_value, 4, "bbox"),
    )


DEEPSEEK_ELEMENT_LOCATE_FORMAT = {
    "resultKey": "point",
    "coordinates": DEEPSEEK_POINT_COORDS,
    "parseRawLocateValue": _parse_deepseek_point_locate_value,
}


DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT = {
    "resultKey": "bbox",
    "coordinates": DEEPSEEK_BBOX_COORDS,
    "parseRawLocateValue": _parse_deepseek_bbox_locate_value,
}


_DEEPSEEK_REF_BOX_PATTERN = (
    r"<(?:｜｜|\|)ref(?:｜｜|\|)>\s*[\s\S]*?\s*<(?:｜｜|\|)/ref(?:｜｜|\|)>"
    r"\s*<(?:｜｜|\|)box(?:｜｜|\|)>\s*([\s\S]*?)\s*<(?:｜｜|\|)/box(?:｜｜|\|)>"
)


_DEEPSEEK_POINT_PATTERN = r"^\s*<(?:｜｜|\|)point(?:｜｜|\|)>\s*([\s\S]*?)\s*<(?:｜｜|\|)/point(?:｜｜|\|)>\s*$"


def _deepseek_element_parse_raw_response(
    content: str, prompt_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    import re as _re

    match = _re.match(_DEEPSEEK_POINT_PATTERN, content)
    if not match:
        raise ValueError(
            "DeepSeek element locate response does not contain a valid "
            "<｜｜point｜｜>value<｜｜/point｜｜> result"
        )
    return {"kind": "located", "target": match.group(1)}


def _deepseek_search_area_parse_raw_response(
    content: str, prompt_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    import re as _re

    raw_boxes = _re.findall(_DEEPSEEK_REF_BOX_PATTERN, content)
    if not raw_boxes:
        raise ValueError(
            "DeepSeek search-area response does not contain a valid "
            "<｜｜ref｜｜>label<｜｜/ref｜｜><｜｜box｜｜>[[x1,y1,x2,y2]]<｜｜/box｜｜> result"
        )
    result: dict[str, Any] = {"kind": "located", "target": raw_boxes[0]}
    if len(raw_boxes) > 1:
        result["references"] = list(raw_boxes[1:])
    return result


def parse_deep_seek_locate_output(content: str) -> dict[str, Any]:
    """Parse a DeepSeek element locate response (upstream parseDeepSeekLocateOutput)."""
    return _deepseek_element_parse_raw_response(content)


def parse_deep_seek_search_area_output(content: str) -> dict[str, Any]:
    """Parse a DeepSeek search-area response (upstream parseDeepSeekSearchAreaOutput)."""
    return _deepseek_search_area_parse_raw_response(content)


def _deepseek_element_response_instructions(prompt_spec: dict[str, Any]) -> str:
    from midscene.core.ai_model.shared.model_locate_result import (
        format_locate_example_value,
    )

    return f"""## Output Format:
Return exactly one {prompt_spec["resultNoun"]} using the following format, without any explanation or additional text:

<｜｜point｜｜>[{prompt_spec["resultValueSchema"]}]<｜｜/point｜｜>

For example:
<｜｜point｜｜>[{format_locate_example_value(prompt_spec["exampleValues"][0])}]<｜｜/point｜｜>

Coordinate values must be integers.
Coordinate requirements: {prompt_spec["resultValueDescription"]}
The origin is the top-left of the full screenshot."""


def _deepseek_search_area_response_instructions(prompt_spec: dict[str, Any]) -> str:
    from midscene.core.ai_model.shared.model_locate_result import (
        format_locate_example_value,
    )

    target_example = format_locate_example_value(prompt_spec["exampleValues"][0])
    reference_example = format_locate_example_value(
        prompt_spec["exampleValues"][1]
        if len(prompt_spec["exampleValues"]) > 1
        else prompt_spec["exampleValues"][0]
    )
    return f"""## Objective:
- Identify the target UI element in the screenshot.
- Identify the reference elements that the description uses to select the target, such as an owner label, row value, column value, nearby text, or relative-position anchor.
- Return a tight {prompt_spec["resultNoun"]} for the target first, followed by a tight {prompt_spec["resultNoun"]} for each reference element.

## Reference Rules:
- If the description explicitly identifies the target through another visible element, you MUST return that visible element as a reference, even if the target appears unique.
- For descriptions like "B in the row whose A is X", B is the target and the visible X is a reference.
- For descriptions like "the icon next to label X", the icon is the target and the visible X is a reference.
- Do not return unrelated landmarks or alternative target candidates.

## Output Format:
Return one or more ref-box pairs using the following format, without any explanation or additional text:

<｜｜ref｜｜>target: concise target description<｜｜/ref｜｜><｜｜box｜｜>[{prompt_spec["resultValueSchema"]}]<｜｜/box｜｜>
<｜｜ref｜｜>reference: concise reference description<｜｜/ref｜｜><｜｜box｜｜>[{prompt_spec["resultValueSchema"]}]<｜｜/box｜｜>

For example:
If the request is "the edit icon in the row whose project name is Apollo", return:
<｜｜ref｜｜>target: edit icon<｜｜/ref｜｜><｜｜box｜｜>[{target_example}]<｜｜/box｜｜>
<｜｜ref｜｜>reference: Apollo<｜｜/ref｜｜><｜｜box｜｜>[{reference_example}]<｜｜/box｜｜>

The first ref-box pair must represent the target element. Every remaining pair must represent a reference element needed to identify the target. If no reference element is needed, return only the target pair. Each pair must contain exactly one {prompt_spec["resultNoun"]}.
Coordinate values must be integers.
Coordinate requirements: {prompt_spec["resultValueDescription"]}
The origin is the top-left of the full screenshot."""


DEEPSEEK_ELEMENT_LOCATE_PROTOCOL = {
    "system_prompt_introduction": (
        "## Role:\nYou are a GUI click grounding agent.\n\n## Objective:\n"
        "- Identify the UI element in the screenshot that matches the user's description.\n"
        "- Return the center point of that element."
    ),
    "build_response_instructions": _deepseek_element_response_instructions,
    "build_user_prompt": (
        lambda description: (
            "Locate the center point of the following UI element: " + description
        )
    ),
    "expected_json_object_response": False,
    "parse_raw_response": _deepseek_element_parse_raw_response,
}


DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL = {
    "system_prompt_introduction": "## Role:\nYou are a GUI grounding agent.",
    "build_response_instructions": _deepseek_search_area_response_instructions,
    "build_user_prompt": (
        lambda description: (
            "Locate the target and the reference elements needed to distinguish it: "
            + description
        )
    ),
    "expected_json_object_response": False,
    "parse_raw_response": _deepseek_search_area_parse_raw_response,
}


deep_seek_element_locate_protocol = DEEPSEEK_ELEMENT_LOCATE_PROTOCOL

deep_seek_search_area_protocol = DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL


__all__ = [
    "DEEPSEEK_ELEMENT_LOCATE_FORMAT",
    "DEEPSEEK_ELEMENT_LOCATE_PROTOCOL",
    "DEEPSEEK_SEARCH_AREA_LOCATE_FORMAT",
    "DEEPSEEK_SEARCH_AREA_LOCATE_PROTOCOL",
    "deep_seek_element_locate_protocol",
    "deep_seek_search_area_protocol",
    "parse_deep_seek_locate_output",
    "parse_deep_seek_search_area_output",
]
