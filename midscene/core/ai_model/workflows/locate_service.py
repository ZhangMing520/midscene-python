"""Locate service with DeepLocate two-stage orchestration.

Synced from upstream packages/core/src/service/index.ts (locate) and
workflows/grounding/section-locate.ts (AiLocateSection).
"""

from typing import Any, Dict, Optional

from loguru import logger

from ..adapters import ModelRuntime
from ..caller import AIResponseParseError, call_generative_ai
from ..env_config import model_family_required_for_locate_message
from ..prompts.locate import build_search_area_locate_system_prompt
from ..semantic_retry import call_ai_and_parse_with_retry, with_semantic_retry_feedback
from .context_utils import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
    prepare_model_image,
    user_prompt_to_string,
)
from .grounding import ai_locate_element
from .search_area import (
    build_search_area_config,
    map_search_area_result_to_original_result,
    merge_search_area_results,
)


async def ai_locate_section(
    context: Any,
    section_description: Any,
    model_runtime: ModelRuntime,
) -> Dict[str, Any]:
    """Locate the section containing the target (first DeepLocate pass).

    Returns {search_area_config?, error?, raw_response, usage}.
    """
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

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "image", "url": prepared_image["image_base64"]},
                {"type": "text", "text": user_instruction_prompt},
            ],
        },
    ]

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
            call_ai=lambda retry_attempt, previous_parse_error=None: call_generative_ai(
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


async def locate_service(
    query_prompt: Any,
    context: Any,
    model_runtime: ModelRuntime,
    deep_locate: bool = False,
    plan_located_element: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The locate orchestration (upstream service.locate).

    With deep_locate enabled, the search area is resolved (plan coordinates,
    section locate, or first-pass locate) and the element locate runs on the
    zoomed-in section image; coordinates are mapped back afterwards.

    Returns {element?, errors?, raw_response, usage, search_area, deep_locate}.
    """
    if not model_runtime.config.get("modelFamily"):
        raise ValueError(
            model_family_required_for_locate_message(model_runtime.config.get("slot"))
        )

    search_area_trace: Dict[str, Any] = {}
    search_config: Optional[Dict[str, Any]] = None

    if deep_locate:
        if plan_located_element and plan_located_element.get("center"):
            # Plan coordinates serve as the search-area hint.
            search_config = build_search_area_config(
                context,
                merge_search_area_results(plan_located_element),
            )
            search_area_trace = {
                "sourceRect": search_config["source_rect"],
                "raw_response": (
                    '{"source": "plan-located-element", '
                    f'"center": {list(plan_located_element["center"])}}}'
                ),
            }
        elif adapter_has_search_area(model_runtime):
            section_response = await ai_locate_section(
                context=context,
                section_description=query_prompt,
                model_runtime=model_runtime,
            )
            search_area_trace = {
                "raw_response": section_response.get("raw_response"),
                "usage": section_response.get("usage"),
            }
            if not section_response.get("search_area_config"):
                raise ValueError(
                    f'cannot find search area for "{user_prompt_to_string(query_prompt)}": '
                    f"{section_response.get('error') or 'unknown search area error'}"
                )
            search_config = section_response["search_area_config"]
            search_area_trace["sourceRect"] = search_config["source_rect"]
        else:
            first_pass = await ai_locate_element(
                target_element_description=query_prompt,
                context=context,
                model_runtime=model_runtime,
            )
            element = first_pass.get("parse_result", {}).get("element")
            if not element or not element.get("center"):
                errors = first_pass.get("parse_result", {}).get("errors") or []
                raise ValueError(
                    f'cannot find search area for "{user_prompt_to_string(query_prompt)}"'
                    + (f": {'; '.join(errors)}" if errors else "")
                )
            search_config = build_search_area_config(
                context, merge_search_area_results(element)
            )
            search_area_trace = {
                "sourceRect": search_config["source_rect"],
                "raw_response": first_pass.get("raw_response"),
                "usage": first_pass.get("usage"),
            }

    locate_image = (
        {
            "imageBase64": search_config["image"]["imageBase64"],
            "width": search_config["image"]["width"],
            "height": search_config["image"]["height"],
        }
        if search_config
        else None
    )
    response = await ai_locate_element(
        target_element_description=query_prompt,
        context=context,
        model_runtime=model_runtime,
        locate_image=locate_image,
    )

    parse_result = response.get("parse_result", {})
    element = parse_result.get("element")
    if element and search_config:
        element = map_search_area_result_to_original_result(
            element, search_config.get("mapping")
        )
        element["description"] = user_prompt_to_string(query_prompt)

    return {
        "element": element,
        "errors": parse_result.get("errors") or [],
        "raw_response": response.get("raw_response"),
        "usage": response.get("usage"),
        "search_area": search_area_trace.get("sourceRect"),
        "search_area_usage": search_area_trace.get("usage"),
        "deep_locate": bool(search_config),
    }


def adapter_has_search_area(model_runtime: ModelRuntime) -> bool:
    """Standard adapters support section locate; custom locate adapters may not."""
    return model_runtime.adapter.locate_kind == "standard"
