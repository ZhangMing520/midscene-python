"""Section locate (first DeepLocate pass).

Synced from upstream packages/core/src/ai-model/workflows/grounding/section-locate.ts.
"""

from typing import Any, Callable, Dict, Optional

from loguru import logger

from midscene.core.ai_model.model_adapter.locate_prompt_order import (
    build_locate_messages,
    multimodal_prompt_to_messages,
)
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.prompt.locate import build_search_area_locate_system_prompt
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.service_caller.semantic_retry import (
    call_ai_and_parse_with_retry,
    with_semantic_retry_feedback,
)
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.model_adapter.image_preprocess import (
    prepare_model_image,
)
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
    user_prompt_to_string,
)
from midscene.core.ai_model.workflows.grounding.search_area import (
    build_search_area_config,
    merge_search_area_results,
)


async def ai_locate_section(
    context: Any,
    section_description: Any,
    model_runtime: ModelRuntime,
    *,
    call_ai: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Locate the section containing the target (first DeepLocate pass).

    Returns {search_area_config?, error?, raw_response, usage}.
    """
    generate_ai = call_ai or call_generative_ai
    adapter = model_runtime.adapter
    search_area_protocol = adapter.locate_protocol["search_area"]
    result_codec = adapter.search_area_result_codec

    system_prompt = build_search_area_locate_system_prompt(
        system_prompt_introduction=search_area_protocol[
            "system_prompt_introduction"
        ],
        response_instructions=search_area_protocol["build_response_instructions"](
            result_codec.prompt_spec
        ),
    )
    user_instruction_prompt = search_area_protocol["build_user_prompt"](
        user_prompt_to_string(section_description)
    )

    prepared_image = prepare_model_image(
        image_base64=ensure_data_url(get_screenshot_base64(context)),
        width=get_shot_size(context)["width"],
        height=get_shot_size(context)["height"],
        policy=(
            {"padBlockSize": adapter.image_pad_block_size}
            if adapter.image_pad_block_size
            else None
        ),
    )

    messages = build_locate_messages(
        adapter.locate_prompt_order,
        {
            "instructions": system_prompt,
            "screenshot": prepared_image["image_base64"],
            "task": user_instruction_prompt,
            "references": multimodal_prompt_to_messages(section_description),
        },
    )

    def parse_response(response: Dict[str, Any]) -> Dict[str, Any]:
        raw_response = response["content"]
        parsed_locate_result = search_area_protocol["parse_raw_response"](
            raw_response, result_codec.prompt_spec
        )
        section_error = parsed_locate_result.get("error")
        if parsed_locate_result["kind"] == "not-found":
            return {"response": response, "section_error": section_error}

        locate_result_context = {
            "preparedSize": prepared_image["prepared_size"],
            "contentSize": prepared_image["content_size"],
        }
        target = result_codec.to_pixel_result(
            parsed_locate_result["target"], locate_result_context
        )
        references = [
            result_codec.to_pixel_result(reference, locate_result_context)
            for reference in parsed_locate_result.get("references", []) or []
        ]
        merged_rect = merge_search_area_results(target, references)
        return {
            "response": response,
            "section_error": section_error,
            "merged_rect": merged_rect,
        }

    def to_parse_error(error: Any, response: Dict[str, Any]) -> AIResponseParseError:
        return AIResponseParseError(
            f"Failed to parse section locate result: {error}",
            response.get("content", ""),
            response.get("usage"),
        )

    try:
        parsed = await call_ai_and_parse_with_retry(
            call_ai=lambda retry_attempt, previous_parse_error=None: generate_ai(
                with_semantic_retry_feedback(messages, previous_parse_error),
                model_runtime,
                {
                    "expectedJsonObjectResponse": search_area_protocol[
                        "expected_json_object_response"
                    ],
                    "semanticRetryAttempt": retry_attempt,
                },
            ),
            parse_response=parse_response,
            to_parse_error=to_parse_error,
            parse_retry_times=model_runtime.config.get("retryCount", 1),
            parse_retry_interval=model_runtime.config.get("retryInterval", 2000),
            on_parse_retry=lambda error, _r: logger.debug(
                f"retrying section locate after coordinate parsing failed: {error}"
            ),
        )
    except AIResponseParseError as call_error:
        return {
            "search_area_config": None,
            "error": call_error.message,
            "raw_response": call_error.raw_response,
            "usage": call_error.usage,
        }
    except Exception as call_error:
        error_message = str(call_error)
        return {
            "search_area_config": None,
            "error": f"AI call error: {error_message}",
            "raw_response": error_message,
        }

    response: Dict[str, Any] = parsed["response"]
    section_error = parsed.get("section_error")
    merged_rect = parsed.get("merged_rect")
    base = {
        "raw_response": response["content"],
        "usage": response.get("usage"),
    }
    if not merged_rect:
        return {**base, "search_area_config": None, "error": section_error}

    try:
        search_area_config = build_search_area_config(context, merged_rect)
        return {**base, "search_area_config": search_area_config, "error": section_error}
    except Exception as error:
        parse_error_message = f"Failed to parse section locate result: {error}"
        error_message = (
            f"{section_error} ({parse_error_message})"
            if section_error
            else parse_error_message
        )
        return {**base, "search_area_config": None, "error": error_message}


__all__ = ["ai_locate_section"]
