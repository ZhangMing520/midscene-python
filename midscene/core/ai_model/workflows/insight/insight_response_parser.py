"""Insight response parser (upstream workflows/insight/insight-response-parser.ts)."""

from typing import Any, Callable, Dict, List, Optional

from midscene.core.ai_model.shared.xml import (
    extract_raw_xml_fragment,
    extract_xml_tag,
)


def parse_insight_response(
    content: str,
    data_output_protocol: Dict[str, Any],
    json_parser: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Parse an insight XML response into {thought?, data, errors?}."""
    observation = extract_xml_tag(content, "observation")
    errors_content = extract_xml_tag(content, "errors")
    raw_data_output = extract_raw_xml_fragment(content, data_output_protocol["tag_names"])
    data = data_output_protocol["parse"](raw_data_output)

    errors: Optional[List[str]] = None
    if errors_content:
        try:
            if json_parser is not None:
                parsed_errors = json_parser(
                    errors_content, {"source": "generic-object"}
                )
            else:
                from midscene.core.ai_model.shared.json import (
                    parse_model_response_json,
                )

                parsed_errors = parse_model_response_json(
                    errors_content, source="generic-object"
                )
            if isinstance(parsed_errors, list):
                errors = parsed_errors
        except Exception:
            # Error details are optional and must not discard valid extracted data.
            pass

    result: Dict[str, Any] = {"data": data}
    if observation:
        result["thought"] = observation
    if errors:
        result["errors"] = errors
    return result


__all__ = ["parse_insight_response"]
