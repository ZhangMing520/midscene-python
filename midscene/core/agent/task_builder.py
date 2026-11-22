"""Action execution and locate resolution (upstream agent/task-builder.ts)."""

import asyncio
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


def _normalize_locate_param(param: Any) -> Dict[str, Any]:
    if isinstance(param, str):
        return {"prompt": param}
    if not isinstance(param, dict):
        raise ValueError("locate parameter must be an object or string")
    normalized = dict(param)
    deep_think = normalized.pop("deepThink", None)
    if "deepLocate" not in normalized and deep_think is not None:
        normalized["deepLocate"] = deep_think
    return normalized


def locate_plan_for_locate(param: Any) -> Dict[str, Any]:
    """Build a Locate planning action (upstream locatePlanForLocate)."""
    return {
        "type": "Locate",
        "param": _normalize_locate_param(param),
        "thought": "",
    }


class _TaskBuilderAgent:
    """Adapter exposing the Agent surface consumed by task_builder helpers."""

    def __init__(self, deps: Dict[str, Any]) -> None:
        self.interface = deps.get("interfaceInstance", deps.get("interface_instance"))
        self.action_space = list(deps.get("actionSpace", deps.get("action_space")) or [])
        self._task_cache = deps.get("taskCache", deps.get("task_cache"))
        self._service = deps.get("service")
        self._get_default_model_runtime = deps.get(
            "getDefaultModelRuntime", deps.get("get_default_model_runtime")
        )
        self.wait_after_action = deps.get(
            "waitAfterAction", deps.get("wait_after_action")
        )
        self._provided_context = None

    def _get_task_cache(self):
        return self._task_cache

    def model_runtime(self, intent: str = "default"):
        if callable(self._get_default_model_runtime):
            return self._get_default_model_runtime()
        return None

    async def _get_ui_context(self, action: str = "locate") -> UIContext:
        if self._provided_context is not None:
            return self._provided_context
        retriever = getattr(self._service, "contextRetrieverFn", None) or getattr(
            self._service, "context_retriever_fn", None
        )
        if callable(retriever):
            return await retriever(None)
        return await self.interface.get_context()

    async def _write_locate_cache(
        self, prompt_str, element, cache, cacheable, replace_index=None
    ):
        return await write_locate_cache(
            self, prompt_str, element, cache, cacheable, replace_index
        )

    async def _locate_for_action(self, locate_param):
        return await locate_for_action(self, locate_param)

    async def _rect_from_cache_feature(self, feature):
        return await rect_from_cache_feature(self, feature)

    async def _run_locate(
        self,
        prompt,
        context,
        deep_locate=False,
        plan_located_element=None,
    ):
        locate_fn = (
            self._service.get("locate")
            if isinstance(self._service, dict)
            else getattr(self._service, "locate", None)
        )
        if callable(locate_fn):
            response = locate_fn(
                {"prompt": prompt},
                {"uiContext": context, "planLocatedElement": plan_located_element},
                self.model_runtime("locate"),
                None,
            )
            if hasattr(response, "__await__"):
                response = await response
            element = response.get("element") if isinstance(response, dict) else None
            if element:
                return to_logical_coords(element, context)
        return await run_locate(
            self,
            prompt,
            context,
            deep_locate=deep_locate,
            plan_located_element=plan_located_element,
        )


class TaskBuilder:
    """Plan-to-executable-task builder (upstream agent/task-builder.ts)."""

    def __init__(self, deps: Dict[str, Any]) -> None:
        self._deps = deps
        self._agent = _TaskBuilderAgent(deps)

    async def build(
        self,
        plans: List[Dict[str, Any]],
        planning_model: Any,
        locate_model: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Convert planning actions into executable task descriptors."""
        options = options or {}
        tasks: List[Dict[str, Any]] = []
        for plan in plans:
            plan_type = plan.get("type")
            if plan_type == "Finished":
                tasks.append(
                    {
                        "type": "Action Space",
                        "subType": "Finished",
                        "param": None,
                        "thought": plan.get("thought"),
                        "executor": _noop_executor,
                    }
                )
                continue
            if plan_type == "Locate":
                locate_param = _normalize_locate_param(plan.get("param"))
                if options.get("cacheable") is not None:
                    locate_param = {
                        **locate_param,
                        "cacheable": options["cacheable"],
                    }
                if options.get("deepLocate"):
                    locate_param.setdefault("deepLocate", True)
                multimodal_prompt = options.get("multimodalPrompt")
                prompt = locate_param.get("prompt")
                if multimodal_prompt and prompt:
                    if isinstance(prompt, str):
                        locate_param["prompt"] = {
                            "prompt": prompt,
                            **multimodal_prompt,
                        }
                    elif isinstance(prompt, dict) and not prompt.get("images"):
                        locate_param["prompt"] = {
                            **prompt,
                            **multimodal_prompt,
                        }

                async def locate_executor(
                    task_context: Dict[str, Any],
                    _param=locate_param,
                ) -> Dict[str, Any]:
                    previous = self._agent._provided_context
                    if task_context.get("uiContext") is not None:
                        self._agent._provided_context = task_context["uiContext"]
                    try:
                        element = await locate_for_action(self._agent, _param)
                    finally:
                        self._agent._provided_context = previous
                    return {"output": {"element": element}}

                tasks.append(
                    {
                        "type": "Planning",
                        "subType": "Locate",
                        "param": locate_param,
                        "thought": plan.get("thought"),
                        "executor": locate_executor,
                    }
                )
                continue

            async def action_executor(
                task_context: Dict[str, Any],
                _plan=plan,
            ) -> Dict[str, Any]:
                definition = find_action_in_action_space_or_throw(
                    plan_type, self._agent.action_space
                )
                delay_before = _definition_field(
                    definition, "delay_before_runner"
                )
                if delay_before is None:
                    delay_before = 200
                delay_after = _definition_field(
                    definition, "delay_after_runner"
                )
                if delay_after is None:
                    wait_after = self._agent.wait_after_action
                    delay_after = 300 if wait_after is None else wait_after
                await _run_before_invoke(
                    self._agent.interface,
                    plan_type,
                    plan.get("param"),
                    delay_before,
                )
                await execute_planning_action(
                    self._agent,
                    _plan,
                    distance_ratio=options.get("distanceRatio"),
                    cacheable=options.get("cacheable"),
                )
                await _run_after_invoke(
                    self._agent.interface,
                    plan_type,
                    plan.get("param"),
                    delay_after,
                )
                return {"output": None}

            tasks.append(
                {
                    "type": "Action Space",
                    "subType": plan_type,
                    "param": plan.get("param"),
                    "thought": plan.get("thought"),
                    "executor": action_executor,
                }
            )
        return {"tasks": tasks}


async def _noop_executor(task_context: Dict[str, Any]) -> None:
    return None


def _definition_field(definition: Any, name: str) -> Any:
    if isinstance(definition, dict):
        return definition.get(name)
    return getattr(definition, name, None)


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def _run_before_invoke(
    interface: Any, action_name: str, param: Any, delay_ms: float
) -> None:
    """Run the before-invoke hook in parallel with the pre-action delay."""
    hook = getattr(interface, "before_invoke_action", None)
    tasks = []
    if callable(hook):

        async def run_hook() -> None:
            try:
                await _maybe_await(hook(action_name, param, None))
            except Exception as error:
                raise RuntimeError(
                    "error in running beforeInvokeAction for "
                    f"{action_name}: {error}"
                ) from error

        tasks.append(run_hook())
    if delay_ms > 0:
        tasks.append(asyncio.sleep(delay_ms / 1000))
    if not tasks:
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def _run_after_invoke(
    interface: Any, action_name: str, param: Any, delay_ms: float
) -> None:
    """Wait the post-action delay, then the default wait and after hook."""
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)
    default_wait = getattr(interface, "default_action_wait", None)
    if callable(default_wait):
        await _maybe_await(default_wait(action_name, param, None))
    hook = getattr(interface, "after_invoke_action", None)
    if callable(hook):
        try:
            await _maybe_await(hook(action_name, param, None))
        except Exception as error:
            raise RuntimeError(
                "error in running afterInvokeAction for "
                f"{action_name}: {error}"
            ) from error


def _with_prompt_display(element: Any, locate_param: Dict[str, Any]) -> Any:
    """Replace the located description with the plan's promptDisplay."""
    prompt_display = locate_param.get("promptDisplay")
    if not prompt_display or not isinstance(element, dict):
        return element
    locate_param["description"] = prompt_display
    return {**element, "description": prompt_display}


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
    cached_pixel = locate_param.get("locatedPixelResult")
    has_plan_coordinates = (
        isinstance(cached_pixel, dict) and bool(cached_pixel.get("center"))
    )
    # Upstream accepts a coordinate-only plan (no prompt) when the plan already
    # carries locatedPixelResult.
    if not prompt and not has_plan_coordinates:
        raise ValueError("locate parameter requires a prompt")

    prompt_str = user_prompt_to_string(prompt) if prompt else ""
    cacheable = locate_param.get("cacheable", True)
    cache = agent._get_task_cache()
    deep_locate = bool(locate_param.get("deepLocate"))

    # Upstream consults the locate cache before choosing between a plan hit and
    # AI locate, so a plan hit can report whether an entry already exists.
    matched: Optional[Dict[str, Any]] = None
    if (
        cache is not None
        and cacheable is not False
        and supports_interface_extension(
            agent.interface, "rect_matches_cache_feature"
        )
    ):
        matched = cache.match_locate_cache(prompt_str)

    # Upstream task-builder: elementFromPlan = locateParam.deepLocate
    # ? undefined : planLocatedElement. With deepLocate the plan
    # coordinates are only a search-area hint for the two-stage locate.
    if has_plan_coordinates and not deep_locate:
        # Fresh plan coordinates take precedence over the cache. Record the
        # feature once for future runs, unless an entry already exists.
        if matched is None:
            await agent._write_locate_cache(
                prompt_str, cached_pixel, cache, cacheable, None
            )
        return _with_prompt_display(cached_pixel, locate_param)

    replace_index: Optional[int] = matched["index"] if matched is not None else None
    if matched is not None:
        rect = await agent._rect_from_cache_feature(matched["cache"])
        if rect is not None:
            return _with_prompt_display(
                {
                    "center": [
                        rect.left + rect.width / 2,
                        rect.top + rect.height / 2,
                    ],
                    "rect": rect,
                    "description": prompt_str,
                },
                locate_param,
            )
        # Stale feature: re-locate and replace this entry in place.

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
    return _with_prompt_display(element, locate_param)


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
