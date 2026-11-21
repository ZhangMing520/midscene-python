"""Default insight protocol (upstream ai-model/model-adapter/default-insight-protocol.ts)."""

from midscene.core.ai_model.shared.json import parse_model_response_json
from midscene.core.ai_model.shared.xml import extract_xml_tag
from typing import Any, Dict

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
