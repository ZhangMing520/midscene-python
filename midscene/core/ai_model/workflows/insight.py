"""Insight workflow: visual understanding / extraction / boolean.

Synced from upstream packages/core/src/ai-model/workflows/insight/
(extraction.ts, boolean.ts, insight-response-parser.ts).
"""

import json
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from ..caller import AIResponseParseError, call_generative_ai
from ..prompts.insight import build_insight_system_prompt, extract_data_query_prompt
from ..protocols import create_default_insight_protocol
from ..semantic_retry import call_ai_and_parse_with_retry, with_semantic_retry_feedback
from ..adapters import ModelRuntime
from ..xml_utils import extract_raw_xml_fragment, extract_xml_tag
from .context_utils import (
    ensure_data_url,
    get_screenshot_base64,
)

_default_insight_protocol = None


def get_default_insight_protocol() -> Dict[str, Any]:
    global _default_insight_protocol
    if _default_insight_protocol is None:
        _default_insight_protocol = create_default_insight_protocol()
    return _default_insight_protocol


def parse_insight_response(
    content: str, data_output_protocol: Dict[str, Any]
) -> Dict[str, Any]:
    """Parse an insight XML response into {thought?, data, errors?}."""
    observation = extract_xml_tag(content, "observation")
    errors_content = extract_xml_tag(content, "errors")
    raw_data_output = extract_raw_xml_fragment(content, data_output_protocol["tag_names"])
    data = data_output_protocol["parse"](raw_data_output)

    errors: Optional[List[str]] = None
    if errors_content:
        try:
            from ..json_utils import parse_model_response_json

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


async def ai_extract_element_info(
    task_type: str,
    data_query: Union[str, Dict[str, str]],
    context: Any,
    model_runtime: ModelRuntime,
    page_description: str = "",
    screenshot_included: bool = True,
    context_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the insight workflow.

    task_type: 'boolean' | 'extract'.
    Returns {parse_result: {thought?, data, errors?}, raw_response, usage, ...}.
    """
    insight_protocol = get_default_insight_protocol()
    data_output = insight_protocol["data_output"]

    boolean_fn = getattr(model_runtime.adapter, "insight_boolean_fn", None)
    if task_type == "boolean" and boolean_fn is not None:
        if not isinstance(data_query, dict) or len(data_query) != 1:
            raise ValueError("Boolean insight tasks require exactly one result field.")
        result_key, demand = next(iter(data_query.items()))
        statement = (
            demand if isinstance(demand, str) else json.dumps(demand, ensure_ascii=False)
        )
        boolean_result = await boolean_fn(
            statement,
            context,
            model_runtime,
            page_description=page_description or "",
            context_text=context_text,
        )
        return {
            "parse_result": {
                "data": {result_key: bool(boolean_result.get("value"))}
            },
            "raw_response": boolean_result.get("raw_response", ""),
            "usage": boolean_result.get("usage"),
            "reasoning_content": None,
        }

    system_prompt = build_insight_system_prompt(
        insight_protocol=insight_protocol,
        screenshot_included=screenshot_included,
        reference_images_included=False,
    )
    screenshot_base64 = ensure_data_url(get_screenshot_base64(context))

    if task_type == "boolean":
        keys = list(data_query.keys()) if isinstance(data_query, dict) else []
        if len(keys) != 1:
            raise ValueError("Boolean insight tasks require exactly one result field.")

    extract_data_prompt_text = extract_data_query_prompt(
        page_description or "",
        data_query,
        context_text,
    )

    user_content: List[Dict[str, Any]] = []
    if screenshot_included:
        user_content.append(
            {
                "type": "text",
                "text": (
                    "This is the current screenshot to evaluate. Unless "
                    "<DATA_DEMAND> explicitly asks for comparison or matching "
                    "against reference images, base your answer on this screenshot "
                    "and its contents when provided."
                ),
            }
        )
        user_content.append({"type": "image", "url": screenshot_base64})

    user_content.append({"type": "text", "text": extract_data_prompt_text})

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    async def call_ai(retry_attempt: int, previous_parse_error: Optional[Any] = None):
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_parse_error),
            model_runtime,
            {"semanticRetryAttempt": retry_attempt},
        )

    def parse_response(response: Dict[str, Any]) -> Dict[str, Any]:
        raw_response = response["content"]
        parse_result = parse_insight_response(raw_response, data_output)
        return {
            "parse_result": parse_result,
            "raw_response": raw_response,
            "raw_assistant_output": response.get("raw_assistant_output"),
            "usage": response.get("usage"),
            "reasoning_content": response.get("reasoning_content"),
        }

    def to_parse_error(parse_error: Any, response: Dict[str, Any]) -> AIResponseParseError:
        return AIResponseParseError(
            f"XML parse error: {parse_error}",
            response.get("content", ""),
            response.get("usage"),
        )

    return await call_ai_and_parse_with_retry(
        call_ai=call_ai,
        parse_response=parse_response,
        to_parse_error=to_parse_error,
        parse_retry_times=model_runtime.config.get("retryCount", 1),
        parse_retry_interval=model_runtime.config.get("retryInterval", 2000),
        on_parse_retry=lambda error, _response: logger.debug(
            f"retrying insight after XML parsing failed: {error}"
        ),
    )
