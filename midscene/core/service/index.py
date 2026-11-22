"""Locate service with DeepLocate two-stage orchestration.

Synced from upstream packages/core/src/service/index.ts (locate). The section
locate pass lives in workflows/grounding/section_locate.py, matching upstream
workflows/grounding/section-locate.ts.
"""

from typing import Any, Dict, Optional
import time

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


class Service:
    """Locate/extract/describe orchestration (upstream ``Service`` class)."""

    def __init__(self, ui_context: Any, opt: Optional[Dict[str, Any]] = None):
        if ui_context is None:
            raise ValueError("uiContext is required for Service")
        opt = opt or {}
        if callable(ui_context) and not isinstance(ui_context, dict):
            self.context_retriever_fn = ui_context
        else:
            async def retrieve() -> Any:
                return ui_context

            self.context_retriever_fn = retrieve
        self.task_info = opt.get("taskInfo")

    async def _resolve_context(self, ui_context: Optional[Any] = None) -> Any:
        if ui_context is not None:
            return ui_context
        context = self.context_retriever_fn()
        if hasattr(context, "__await__"):
            context = await context
        return context

    async def locate(
        self,
        query: Dict[str, Any],
        opt: Optional[Dict[str, Any]] = None,
        model_runtime: Optional[ModelRuntime] = None,
        abort_signal: Optional[Any] = None,
    ) -> Dict[str, Any]:
        from midscene.core.service.utils import create_service_dump

        opt = opt or {}
        query_prompt = query.get("prompt")
        if not query_prompt:
            raise ValueError("query is required for locate")
        start_time = int(time.time() * 1000)
        context = await self._resolve_context(opt.get("uiContext"))
        response = await locate_service(
            query_prompt,
            context,
            model_runtime,
            bool(query.get("deepLocate")),
            opt.get("planLocatedElement"),
        )
        task_info = {
            **(self.task_info or {}),
            "durationMs": int(time.time() * 1000) - start_time,
            "rawResponse": response.get("raw_response"),
            "usage": response.get("usage"),
            "searchArea": response.get("search_area"),
            "searchAreaUsage": response.get("search_area_usage"),
        }
        element = response.get("element")
        dump = create_service_dump(
            {
                "type": "locate",
                "userQuery": {"element": query_prompt},
                "matchedElement": [element] if element else [],
                "data": None,
                "taskInfo": task_info,
                "deepLocate": bool(response.get("deep_locate")),
                "error": (
                    "\n".join(response.get("errors") or [])
                    if response.get("errors")
                    else None
                ),
            }
        )
        if response.get("errors"):
            from midscene.core.errors import ServiceError

            raise ServiceError("\n".join(response["errors"]), dump)
        return {"element": element, "dump": dump}

    async def extract(
        self,
        data_demand: Any,
        model_runtime: Optional[ModelRuntime],
        task_type: str,
        opt: Optional[Dict[str, Any]] = None,
        page_description: Optional[str] = None,
        multimodal_prompt: Optional[Dict[str, Any]] = None,
        ui_context: Optional[Any] = None,
        execution_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from midscene.core.ai_model.workflows.insight import (
            ai_extract_element_info,
        )
        from midscene.core.service.utils import create_service_dump

        opt = opt or {}
        start_time = int(time.time() * 1000)
        context = await self._resolve_context(ui_context)
        response = await ai_extract_element_info(
            task_type,
            data_demand,
            context,
            model_runtime,
            page_description or "",
            bool(opt.get("screenshotIncluded", True)),
            opt.get("context"),
        )
        parse_result = response.get("parse_result") or {}
        error_log = None
        if parse_result.get("errors"):
            error_log = "AI response error: \n" + "\n".join(
                parse_result["errors"]
            )
        task_info = {
            **(self.task_info or {}),
            "durationMs": int(time.time() * 1000) - start_time,
            "rawResponse": response.get("raw_response"),
            "formatResponse": parse_result,
            "usage": response.get("usage"),
        }
        data = parse_result.get("data")
        dump = create_service_dump(
            {
                "type": task_type,
                "userQuery": {"dataDemand": data_demand},
                "data": data,
                "taskInfo": task_info,
                "error": error_log,
            }
        )
        if error_log and not data:
            from midscene.core.errors import ServiceError

            raise ServiceError(error_log, dump)
        return {
            "data": data,
            "thought": parse_result.get("thought"),
            "usage": response.get("usage"),
            "reasoning_content": response.get("reasoning_content"),
            "dump": dump,
        }

    async def describe(
        self,
        target: Any,
        model_runtime: Optional[ModelRuntime],
        opt: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from midscene.core.service.describe import ai_describe_element

        opt = opt or {}
        context = await self._resolve_context(opt.get("uiContext"))
        response = await ai_describe_element(
            context, target, model_runtime, bool(opt.get("deepDescribe"))
        )
        return response


__all__ = [
    "Service",
    "adapter_has_search_area",
    "ai_locate_section",
    "locate_service",
]
