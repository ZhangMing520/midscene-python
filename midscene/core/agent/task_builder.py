"""Action execution and locate resolution (upstream agent/task-builder.ts)."""

import time
from typing import Any, Dict, List, Optional

import yaml as pyyaml
from loguru import logger

from midscene.core.agent.common import TASK_TYPE_LOCATE
from midscene.core.agent.ui_utils import to_logical_coords
from midscene.core.agent.task_cache import TaskCache
from midscene.core.agent.tasks import build_action_report_task
from midscene.core.agent.utils import _strip_runtime_locate_result
from midscene.core.ai_model.shared.multimodal_prompt import user_prompt_to_string
from midscene.core.device import (
    find_action_in_action_space_or_throw,
    scale_action_distances,
)
from midscene.core.errors import LocateFailureError
from midscene.core.service import locate_service
from midscene.core.types import TUserPrompt, UIContext, supports_interface_extension

async def execute_planning_action(
    agent,
    action: Dict[str, Any],
    distance_ratio: Optional[float] = None,
    cacheable: Optional[bool] = None,
) -> None:
    action_type = action.get("type")
    definition = find_action_in_action_space_or_throw(action_type, agent.action_space)
    param = action.get("param") or {}
    if distance_ratio is not None:
        param = scale_action_distances(param, definition, distance_ratio)
        action["param"] = param
    if cacheable is not None:
        locate_fields = (
            definition.get("locate_fields")
            if isinstance(definition, dict)
            else definition.locate_fields
        ) or []
        exec_param = dict(param)
        for field in locate_fields:
            locate_param = exec_param.get(field)
            if isinstance(locate_param, dict):
                exec_param[field] = {**locate_param, "cacheable": cacheable}
    else:
        exec_param = param
    if definition.execute is None:
        raise NotImplementedError(f"Action {action_type} has no executor")
    logger.info(f"Executing action {action_type}: {param}")
    await definition.execute(exec_param, agent.interface, agent._locate_for_action)


async def locate_for_action(agent, locate_param: Any) -> Dict[str, Any]:
    """Resolve a planning locate parameter to pixel coordinates.

    Locate-cache order mirrors upstream task-builder: plan coordinates win,
    then a cached xpath is resolved, then AI locate runs, and a successful
    locate writes the element feature back to the cache.
    """
    if not isinstance(locate_param, dict):
        raise ValueError(f"locate parameter must be an object, got {locate_param!r}")
    prompt = locate_param.get("prompt")
    if not prompt:
        raise ValueError("locate parameter requires a prompt")

    prompt_str = user_prompt_to_string(prompt)
    cacheable = locate_param.get("cacheable", True)
    cache = agent._get_task_cache()
    deep_locate = bool(locate_param.get("deepLocate"))

    cached_pixel = locate_param.get("locatedPixelResult")
    # Upstream task-builder: elementFromPlan = locateParam.deepLocate
    # ? undefined : planLocatedElement. With deepLocate the plan
    # coordinates are only a search-area hint for the two-stage locate.
    if cached_pixel and cached_pixel.get("center") and not deep_locate:
        # Fresh plan coordinates take precedence over the cache. Record the
        # feature once for future runs, unless an entry already exists.
        if not (cache is not None and cache.has_locate_cache(prompt_str)):
            await agent._write_locate_cache(
                prompt_str, cached_pixel, cache, cacheable, None
            )
        return cached_pixel

    replace_index: Optional[int] = None
    if (
        cache is not None
        and cacheable is not False
        and supports_interface_extension(
            agent.interface, "rect_matches_cache_feature"
        )
    ):
        matched = cache.match_locate_cache(prompt_str)
        if matched is not None:
            rect = await agent._rect_from_cache_feature(matched["cache"])
            if rect is not None:
                return {
                    "center": [
                        rect.left + rect.width / 2,
                        rect.top + rect.height / 2,
                    ],
                    "rect": rect,
                    "description": prompt_str,
                }
            # Stale feature: re-locate and replace this entry in place.
            replace_index = matched["index"]

    context = await agent._get_ui_context("locate")
    element = await agent._run_locate(
        prompt,
        context,
        deep_locate=deep_locate,
        plan_located_element=cached_pixel if deep_locate else None,
    )
    await agent._write_locate_cache(
        prompt_str, element, cache, cacheable, replace_index
    )
    return element


async def run_locate(
    agent,
    prompt: TUserPrompt,
    context: UIContext,
    deep_locate: bool = False,
    plan_located_element: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime = agent._resolve_runtime(TASK_TYPE_LOCATE)
    response = await locate_service(
        query_prompt=prompt,
        context=context,
        model_runtime=runtime,
        deep_locate=deep_locate,
        plan_located_element=plan_located_element,
    )
    element = response.get("element")
    if not element or not element.get("center"):
        errors = response.get("errors") or ["element not found"]
        raise LocateFailureError(
            f"Element not found : {user_prompt_to_string(prompt)}"
            + (f" ({'; '.join(errors)})" if errors else "")
        )
    return to_logical_coords(element, context)


async def rect_from_cache_feature(agent, feature: Dict[str, Any]):
    try:
        return await agent.interface.rect_matches_cache_feature(feature)
    except NotImplementedError:
        return None
    except Exception as e:
        logger.warning(f"Failed to resolve locate cache feature: {e}")
        return None


async def write_locate_cache(
    agent,
    prompt_str: str,
    element: Dict[str, Any],
    cache: Optional[TaskCache],
    cacheable: Any,
    replace_index: Optional[int] = None,
) -> None:
    if (
        cache is None
        or cacheable is False
        or not supports_interface_extension(
            agent.interface, "cache_feature_for_point"
        )
    ):
        return
    center = element.get("center") if isinstance(element, dict) else None
    if not center:
        return
    options: Dict[str, Any] = {"target_description": prompt_str}
    try:
        # Upstream AiJudgeOrderSensitive always uses the default slot.
        options["model_runtime"] = agent.model_runtime("default")
    except Exception as e:
        # Without a runtime the interface falls back to order-insensitive paths.
        logger.debug(f"order-sensitive judge unavailable: {e}")
    try:
        feature = await agent.interface.cache_feature_for_point(
            [float(center[0]), float(center[1])], options
        )
    except NotImplementedError:
        return
    except Exception as e:
        logger.warning(f"Failed to build locate cache feature: {e}")
        return
    if isinstance(feature, dict) and feature.get("xpaths"):
        cache.append_locate_cache(prompt_str, feature, replace_index)


async def replay_cached_plan(
    agent,
    cached_entry: Dict[str, Any],
    reported: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Replay a cached YAML plan; returns True on success, False to fall
    back to AI planning (upstream loadYamlFlowAsPlanning)."""
    yaml_flow = cached_entry.get("yamlWorkflow") or cached_entry.get("yaml_workflow")
    if not yaml_flow:
        return False
    parsed = pyyaml.safe_load(yaml_flow)
    actions: List[Dict[str, Any]] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
        for task in parsed["tasks"]:
            flow = task.get("flow") if isinstance(task, dict) else None
            if isinstance(flow, list):
                actions.extend(flow)
    elif isinstance(parsed, list):
        actions = parsed
    else:
        return False

    for action_dict in actions:
        if not isinstance(action_dict, dict) or "type" not in action_dict:
            return False
        action = {
            "type": action_dict["type"],
            "param": _strip_runtime_locate_result(dict(action_dict)),
        }
        action["param"].pop("type", None)
        started_at = time.time()
        await agent._execute_planning_action(action)
        if reported is not None:
            reported.append(
                build_action_report_task(
                    action, started_at, time.time()
                )
            )
    logger.info("Cached plan replay completed")
    return True
