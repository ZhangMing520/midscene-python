"""Insight workflow: visual understanding / extraction / boolean.

Synced from upstream packages/core/src/ai-model/workflows/insight/
(extraction.ts, boolean.ts, insight-response-parser.ts).
"""

from typing import Any

from loguru import logger

from midscene.core.ai_model.model_adapter.insight import (
    get_default_insight_protocol,  # noqa: F401 (re-export)
    resolve_insight,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.prompt.insight import (
    build_insight_system_prompt,
    extract_data_query_prompt,
)
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    get_screenshot_base64,
)
from midscene.core.ai_model.workflows.insight.boolean import extract_boolean
from midscene.core.ai_model.workflows.insight.insight_response_parser import (
    parse_insight_response,
)


async def ai_extract_element_info(
    task_type: str,
    data_query: str | dict[str, str],
    context: Any,
    model_runtime: ModelRuntime,
    page_description: str = "",
    screenshot_included: bool = True,
    context_text: str | None = None,
    screenshot_sequence: list[str] | None = None,
) -> dict[str, Any]:
    """Run the insight workflow.

    task_type: 'boolean' | 'extract'.
    Returns {parse_result: {thought?, data, errors?}, raw_response, usage, ...}.
    """
    insight_adapter = resolve_insight(model_runtime.adapter)
    insight_protocol = insight_adapter["protocol"]
    data_output = insight_protocol["data_output"]

    boolean_fn = insight_adapter["boolean_fn"]
    if task_type == "boolean" and boolean_fn is not None:
        return await extract_boolean(
            boolean_fn,
            data_query,
            context,
            model_runtime,
            page_description=page_description or "",
            context_text=context_text,
        )

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

    user_content: list[dict[str, Any]] = []
    if screenshot_included:
        frames = screenshot_sequence or []
        if len(frames) > 1:
            user_content.append(
                {
                    "type": "text",
                    "text": (
                        f"The following {len(frames)} images are consecutive "
                        "screenshots captured over a time window, ordered from "
                        "earliest to latest (Frame 1 is first, Frame "
                        f"{len(frames)} is last). They record what appeared on "
                        "screen during that window. Some UI elements such as "
                        "toasts, banners, or transitions may appear only in "
                        "certain frames and be gone by later ones. Interpret "
                        "the temporal scope from the statement or question "
                        "itself: if it asks whether something appeared at any "
                        "point, inspect the whole sequence; if it asks about "
                        "the final or current state, use the relevant later "
                        "frame; if it asks about a change or sequence, compare "
                        "frames in order. Unless <DATA_DEMAND> explicitly asks "
                        "for comparison or matching against reference images, "
                        "base your answer on these screenshots and their contents."
                    ),
                }
            )
            for index, frame in enumerate(frames):
                user_content.append(
                    {"type": "text", "text": f"Frame {index + 1}/{len(frames)}"}
                )
                user_content.append({"type": "image", "url": frame})
        else:
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

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    async def call_ai(
        retry_attempt: int, previous_parse_error: Any | None = None
    ) -> dict[str, Any]:
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_parse_error),
            model_runtime,
            {"semanticRetryAttempt": retry_attempt},
        )

    def parse_response(response: dict[str, Any]) -> dict[str, Any]:
        raw_response = response["content"]
        parse_result = parse_insight_response(raw_response, data_output)
        return {
            "parse_result": parse_result,
            "raw_response": raw_response,
            "raw_assistant_output": response.get("raw_assistant_output"),
            "usage": response.get("usage"),
            "reasoning_content": response.get("reasoning_content"),
        }

    def to_parse_error(
        parse_error: Any, response: dict[str, Any]
    ) -> AIResponseParseError:
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
