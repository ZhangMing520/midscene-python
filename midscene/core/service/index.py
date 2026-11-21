"""Locate service with DeepLocate two-stage orchestration.

Synced from upstream packages/core/src/service/index.ts (locate). The section
locate pass lives in workflows/grounding/section_locate.py, matching upstream
workflows/grounding/section-locate.ts.
"""

from typing import Any, Dict, Optional

from midscene.core.ai_model.models.registry import ModelRuntime
from midscene.core.ai_model.service_caller.call_ai import call_generative_ai
from midscene.core.ai_model.shared.multimodal_prompt import user_prompt_to_string
from midscene.core.ai_model.workflows.grounding.locate import ai_locate_element
from midscene.core.ai_model.workflows.grounding.search_area import (
    build_search_area_config,
    map_search_area_result_to_original_result,
    merge_search_area_results,
)
from midscene.core.ai_model.workflows.grounding.section_locate import (
    ai_locate_section as _ai_locate_section,
)
from midscene.shared.env import model_family_required_for_locate_message


async def ai_locate_section(
    context: Any,
    section_description: Any,
    model_runtime: ModelRuntime,
) -> Dict[str, Any]:
    """Delegate to the grounding section locate workflow.

    `call_generative_ai` is read from this module so callers that patch the
    service module keep intercepting the model call.
    """
    return await _ai_locate_section(
        context,
        section_description,
        model_runtime,
        call_ai=call_generative_ai,
    )


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
