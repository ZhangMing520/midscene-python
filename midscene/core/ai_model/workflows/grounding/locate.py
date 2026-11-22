"""Grounding workflow: locate a UI element by description.

Synced from upstream packages/core/src/ai-model/workflows/grounding/locate.ts.
"""

from typing import Any, Dict, Optional

from loguru import logger

from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.model_adapter.locate import resolve_locate
from midscene.core.ai_model.prompt.locate import build_element_locate_system_prompt
from midscene.core.ai_model.service_caller.semantic_retry import call_ai_and_parse_with_retry, with_semantic_retry_feedback
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    user_prompt_to_string,
)
from midscene.core.ai_model.workflows.grounding.types import (
    LocateImage,
    LocateModelResponse,
    LocateResult,
)
from midscene.core.ai_model.workflows.grounding.search_area_mapping import (
    map_search_area_result_to_original_result,
)
from midscene.core.ai_model.workflows.grounding.utils import (
    format_locate_model_context,
    prepare_locate_model_input,
)


async def ai_locate_element(
    target_element_description: Any,
    context: Any,
    model_runtime: ModelRuntime,
    locate_image: Optional[LocateImage] = None,
    abort_signal: Optional[Any] = None,
    search_config: Optional[Dict[str, Any]] = None,
) -> LocateResult:
    """Locate an element by description; returns a LocateResult-like dict:

    {parse_result: {element: {center, rect, description}|None, errors: [...]},
     raw_response, usage, reasoning_content}
    """
    description_text = user_prompt_to_string(target_element_description)
    if not description_text:
        raise ValueError("cannot find the target element description")

    if locate_image is None:
        if search_config and search_config.get("image"):
            search_image = search_config["image"]
            locate_image = {
                "imageBase64": search_image["imageBase64"],
                "width": search_image["width"],
                "height": search_image["height"],
            }
        else:
            shot_size = _get_size(context)
            locate_image = {
                "imageBase64": _get_screenshot(context),
                "width": shot_size["width"],
                "height": shot_size["height"],
            }

    adapter = model_runtime.adapter
    locate_adapter = resolve_locate(adapter)
    if locate_adapter["kind"] == "custom":
        locate_fn = locate_adapter["locate_fn"]
        response: LocateModelResponse = await locate_fn(
            target_element_description=target_element_description,
            locate_image=locate_image,
            model_runtime=model_runtime,
        )
        located = response.get("locatedPixelResult")
        element = None
        if located and located.get("center"):
            mapping = (search_config or {}).get("mapping")
            if mapping:
                element = {
                    **map_search_area_result_to_original_result(located, mapping),
                    "description": description_text,
                }
            else:
                element = {
                    "center": located["center"],
                    "description": description_text,
                }
                if located.get("rect"):
                    element["rect"] = located["rect"]
        return {
            "parse_result": {
                "element": element,
                "errors": response.get("errors") or [],
            },
            "raw_response": response.get("raw_response"),
            "usage": response.get("usage"),
            "reasoning_content": response.get("reasoningContent")
            or response.get("reasoning_content"),
        }

    element_adapter = locate_adapter["element"]
    protocol = element_adapter["protocol"]
    result_codec = element_adapter["result_codec"]

    system_prompt = build_element_locate_system_prompt(
        system_prompt_introduction=protocol["system_prompt_introduction"],
        response_instructions=protocol["build_response_instructions"](
            result_codec.prompt_spec
        ),
    )
    user_instruction_prompt = protocol["build_user_prompt"](description_text)

    prepared = prepare_locate_model_input(
        locate_image=locate_image,
        target_description=target_element_description,
        system_prompt=system_prompt,
        user_prompt=user_instruction_prompt,
        image_preprocess=(
            {"padBlockSize": adapter.image_pad_block_size}
            if adapter.image_pad_block_size
            else None
        ),
        prompt_order=adapter.locate_prompt_order,
    )
    messages = prepared["messages"]
    prepared_image = prepared["prepared_image"]

    def build_base(
        raw_response: str,
        usage: Optional[Dict[str, Any]],
        reasoning_content: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "raw_response": raw_response,
            "usage": usage,
            "reasoning_content": reasoning_content,
        }

    async def call_ai(retry_attempt: int, previous_parse_error: Optional[Any] = None):
        return await call_generative_ai(
            with_semantic_retry_feedback(messages, previous_parse_error),
            model_runtime,
            {
                "expectedJsonObjectResponse": protocol["expected_json_object_response"],
                "semanticRetryAttempt": retry_attempt,
            },
        )

    def parse_response(response: Dict[str, Any]) -> Dict[str, Any]:
        raw_response = response["content"]
        parsed_locate_result = protocol["parse_raw_response"](
            raw_response, result_codec.prompt_spec
        )
        locate_error = parsed_locate_result.get("error")
        base = build_base(
            raw_response,
            response.get("usage"),
            response.get("reasoning_content"),
        )

        if parsed_locate_result["kind"] == "not-found":
            return {
                **base,
                "parse_result": {
                    "element": None,
                    "errors": [locate_error] if locate_error else [],
                },
            }

        try:
            result = result_codec.to_pixel_result(
                parsed_locate_result["target"],
                {
                    "preparedSize": prepared_image["prepared_size"],
                    "contentSize": prepared_image["content_size"],
                },
            )
            return {
                **base,
                "parse_result": {
                    "element": {
                        "center": result["center"],
                        "rect": result.get("rect"),
                        "description": description_text,
                    },
                    "errors": [],
                },
            }
        except Exception as error:
            message = "\n".join(
                part
                for part in (
                    f"error in locate result: {locate_error}" if locate_error else None,
                    f"coordinate parsing error: {error}",
                    format_locate_model_context(model_runtime),
                )
                if part
            )
            raise ValueError(message) from error

    def to_parse_error(error: Any, response: Dict[str, Any]) -> AIResponseParseError:
        return AIResponseParseError(
            f"Failed to parse locate result: {error}",
            response.get("content", ""),
            response.get("usage"),
        )

    try:
        result = await call_ai_and_parse_with_retry(
            call_ai=call_ai,
            parse_response=parse_response,
            to_parse_error=to_parse_error,
            parse_retry_times=model_runtime.config.get("retryCount", 1),
            parse_retry_interval=model_runtime.config.get("retryInterval", 2000),
            on_parse_retry=lambda error, _response: logger.debug(
                f"retrying locate after coordinate parsing failed: {error}"
            ),
        )
        return result
    except AIResponseParseError as call_error:
        return {
            "raw_response": call_error.raw_response,
            "usage": call_error.usage,
            "reasoning_content": call_error.reasoning_content,
            "parse_result": {
                "element": None,
                "errors": [call_error.message],
            },
        }
    except Exception as call_error:
        error_message = str(call_error)
        return {
            "raw_response": error_message,
            "usage": None,
            "parse_result": {
                "element": None,
                "errors": [f"AI call error: {error_message}"],
            },
        }


def _get_screenshot(context: Any) -> str:
    from midscene.core.ai_model.shared.multimodal_prompt import get_screenshot_base64

    return ensure_data_url(get_screenshot_base64(context))


def _get_size(context: Any) -> Dict[str, int]:
    from midscene.core.ai_model.shared.multimodal_prompt import get_shot_size

    return get_shot_size(context)
