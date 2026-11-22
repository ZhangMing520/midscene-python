"""Element description workflow (upstream service.describe + prompt/describe.ts).

The screenshot is annotated with a temporary target marker (ring + crosshair,
or a bordered rect) before it goes to the model, because the prompt asks the
model to describe "the element indicated by the marker".
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Union

from midscene.shared.img import box_select, transform
from midscene.core.ai_model.service_caller.types import AIResponseParseError
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.shared.json import parse_model_response_json
from midscene.core.ai_model.prompt.describe import element_describer_instruction
from midscene.core.ai_model.service_caller.semantic_retry import call_ai_and_parse_with_retry, with_semantic_retry_feedback
from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.shared.multimodal_prompt import (
    ensure_data_url,
    get_screenshot_base64,
    get_shot_size,
)
from midscene.core.service.utils import (
    get_describe_deep_context_areas,
    get_describe_marker_border_thickness,
    get_describe_marker_rect,
    get_rect_in_crop,
    recover_describe_response_from_parse_error,
)

DESCRIBE_DEFAULT_RECT_SIZE = 30
DESCRIBE_CROP_MAX_LONG_EDGE = 1000
DESCRIBE_CROP_UPSCALE_MAX_RATIO = 2.0


def _rect_from_point(point: Sequence[float]) -> Dict[str, float]:
    half = DESCRIBE_DEFAULT_RECT_SIZE / 2
    return {
        "left": math.floor(float(point[0]) - half),
        "top": math.floor(float(point[1]) - half),
        "width": DESCRIBE_DEFAULT_RECT_SIZE,
        "height": DESCRIBE_DEFAULT_RECT_SIZE,
    }


def _marked_payload(
    screenshot: str,
    is_point: bool,
    point: Optional[Dict[str, float]],
    rect: Dict[str, float],
) -> str:
    if is_point and point is not None:
        return box_select.composite_point_marker(screenshot, point)
    return box_select.composite_rect_marker(
        screenshot,
        get_describe_marker_rect(rect),
        get_describe_marker_border_thickness(rect),
    )


def _deep_context_images(
    screenshot: str,
    rect: Dict[str, float],
    shot_size: Dict[str, int],
    is_point: bool,
    point: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Focused crop around the target, marked again and upscaled when small."""
    area = get_describe_deep_context_areas(rect, shot_size)[0]["rect"]
    cropped, crop_size = transform.crop_by_rect(screenshot, area)
    if is_point and point is not None:
        marked = box_select.composite_point_marker(
            cropped,
            {"x": point["x"] - area["left"], "y": point["y"] - area["top"]},
        )
    else:
        target_in_crop = get_rect_in_crop(rect, area, crop_size)
        marked = box_select.composite_rect_marker(
            cropped,
            get_describe_marker_rect(target_in_crop),
            get_describe_marker_border_thickness(target_in_crop),
        )
    resized = transform.resize_long_edge(
        marked, DESCRIBE_CROP_MAX_LONG_EDGE, DESCRIBE_CROP_UPSCALE_MAX_RATIO
    )
    return [
        {
            "type": "text",
            "text": (
                "Image 2: focused detail crop around the target, for reading "
                "text, icon shape, and exact local boundaries."
            ),
        },
        {"type": "image", "url": resized or marked},
    ]


def build_describe_messages(
    screenshot: str,
    target: Union[Sequence[float], Dict[str, float]],
    shot_size: Dict[str, int],
    deep_describe: bool = False,
) -> List[Dict[str, Any]]:
    """Messages for one describe call (upstream service.describe)."""
    is_point = not isinstance(target, dict)
    if is_point:
        point = {"x": float(target[0]), "y": float(target[1])}
        rect = _rect_from_point(target)
    else:
        point = None
        rect = {
            "left": float(target["left"]),
            "top": float(target["top"]),
            "width": float(target["width"]),
            "height": float(target["height"]),
        }

    payload = _marked_payload(screenshot, is_point, point, rect)
    if deep_describe:
        user_content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Use these images together to describe the real UI target "
                    "marked by the temporary target marker. Do not describe the "
                    "marker itself."
                ),
            },
            {
                "type": "text",
                "text": (
                    "Image 1: full screenshot overview with the target marker, "
                    "for page position and ownership context."
                ),
            },
            {"type": "image", "url": payload},
        ]
        user_content.extend(
            _deep_context_images(screenshot, rect, shot_size, is_point, point)
        )
    else:
        user_content = [
            {
                "type": "text",
                "text": (
                    "Full screenshot with a temporary target marker (a ring "
                    "with a crosshair) marking the target:"
                ),
            },
            {"type": "image", "url": payload},
        ]

    return [
        {"role": "system", "content": element_describer_instruction()},
        {"role": "user", "content": user_content},
    ]


async def ai_describe_element(
    context: Any,
    target: Union[Sequence[float], Dict[str, float]],
    model_runtime: ModelRuntime,
    deep_describe: bool = False,
) -> Dict[str, Any]:
    """Describe the element at a point or rect (upstream Service.describe).

    Returns {description, usage, raw_response, thought?}.
    """
    screenshot = ensure_data_url(get_screenshot_base64(context))
    shot_size = get_shot_size(context)
    messages = build_describe_messages(
        screenshot, target, shot_size, deep_describe
    )

    async def call_ai(retry_attempt: int, previous_parse_error: Optional[Any] = None):
        try:
            return await call_generative_ai(
                with_semantic_retry_feedback(messages, previous_parse_error),
                model_runtime,
                {
                    "semanticRetryAttempt": retry_attempt,
                    "expectedJsonObjectResponse": True,
                },
            )
        except Exception as error:
            # Upstream recovers a description from a malformed JSON response
            # instead of failing the whole describe call.
            recovered = recover_describe_response_from_parse_error(error)
            if recovered is None:
                raise
            return {"_recovered": recovered}

    def parse_response(response: Dict[str, Any]) -> Dict[str, Any]:
        if "_recovered" in response:
            return response["_recovered"]
        raw_response = response["content"]
        parsed = parse_model_response_json(raw_response, source="generic-object")
        if not isinstance(parsed, dict):
            raise ValueError("describe response is not a JSON object")
        if parsed.get("error"):
            raise ValueError(f"describe failed: {parsed['error']}")
        description = parsed.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("failed to describe the element")
        result: Dict[str, Any] = {
            "description": description.strip(),
            "usage": response.get("usage"),
            "raw_response": raw_response,
        }
        if response.get("reasoning_content"):
            result["reasoning_content"] = response["reasoning_content"]
        return result

    def to_parse_error(error: Any, response: Dict[str, Any]) -> AIResponseParseError:
        return AIResponseParseError(
            f"Failed to parse describe result: {error}",
            response.get("content", ""),
            response.get("usage"),
        )

    return await call_ai_and_parse_with_retry(
        call_ai=call_ai,
        parse_response=parse_response,
        to_parse_error=to_parse_error,
        parse_retry_times=model_runtime.config.get("retryCount", 1),
        parse_retry_interval=model_runtime.config.get("retryInterval", 2000),
    )


__all__ = ["ai_describe_element", "build_describe_messages"]