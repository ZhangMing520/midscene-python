"""
Agent - Core automation controller that orchestrates AI and device interactions.

Fully aligned with upstream web-infra-dev/midscene v1.17.4 (packages/core/src/agent):
- aiAct: plan -> execute -> feedback loop with 'fast' | 'balance' | 'deepThink'
  effort modes, sub-goal tracking (deepThink), delegation (Jev -> default model),
  replanning cycle limit and plan caching
- aiTap/aiRightClick/aiMiddleClick/aiDoubleClick/aiHover/aiInput/aiKeyboardPress/
  aiScroll/aiLongPress/aiClearInput: single locate call + device action
- aiQuery/aiBoolean/aiNumber/aiString/aiAsk/aiAssert/aiWaitFor/aiLocate
- locate: DeepLocate two-stage orchestration (section locate + zoomed search)
"""

import asyncio
import os
import time
from typing import Any, Callable, Dict, List, Optional, Union

import yaml as pyyaml
from loguru import logger

from .actions import (
    DeviceAction,
    _supports,
    build_action_space_for,
    find_action_in_action_space_or_throw,
)
from .ai_model.adapters import ModelRuntime, get_model_runtime, resolve_model_for_task_type
from .ai_model.env_config import (
    ModelConfigManager,
    get_global_model_config_manager,
    is_cache_enabled,
)
from .ai_model.workflows import (
    ConversationHistory,
    ai_extract_element_info,
    standard_plan,
)
from .ai_model.workflows.context_utils import user_prompt_to_string
from .ai_model.workflows.jev import jev_plan
from .ai_model.workflows.locate_service import locate_service
from .task_cache import TaskCache
from .dump import ExecutionDumpBuilder, build_execution_task, get_report_file_name
from .types import (
    AbstractInterface,
    AgentOptions,
    InterfaceType,
    LocateResult,
    ScrollParam,
    TUserPrompt,
    UIContext,
    supports_interface_extension,
)

# Task types for model-fallback resolution (upstream ModelTaskType)
TASK_TYPE_PLANNING = "planning"
TASK_TYPE_LOCATE = "locate"
TASK_TYPE_EXTRACT = "extract"
TASK_TYPE_BOOLEAN = "boolean"

MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP = 5
DEFAULT_WAIT_AFTER_ACTION_MS = 300

AGENT_AI_CONTEXT_KEYS = (
    "default",
    "aiAct",
    "aiTap",
    "aiRightClick",
    "aiMiddleClick",
    "aiDoubleClick",
    "aiHover",
    "aiInput",
    "aiKeyboardPress",
    "aiScroll",
    "aiLongPress",
    "aiClearInput",
    "aiLocate",
    "aiQuery",
    "aiBoolean",
    "aiNumber",
    "aiString",
    "aiAsk",
    "aiAssert",
    "aiWaitFor",
)


class LocateFailureError(Exception):
    """Raised when the model cannot locate the requested element."""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _strip_runtime_locate_result(value: Any) -> Any:
    """Drop screenshot-space coordinates before persisting/replaying a plan.

    Upstream `dumpActionParam` keeps only the locate prompt in cached flows;
    reusing `locatedPixelResult` from an older screenshot clicks stale
    coordinates.
    """
    if isinstance(value, dict):
        return {
            key: _strip_runtime_locate_result(item)
            for key, item in value.items()
            if key != "locatedPixelResult"
        }
    if isinstance(value, list):
        return [_strip_runtime_locate_result(item) for item in value]
    return value


def _env_number(key: str) -> Optional[int]:
    raw = os.environ.get(key)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _extract_typed_query_result(data: Any, key: str) -> Any:
    """Extract a typed query value like upstream createTypeQueryTask.

    Plain strings pass through; dicts prefer the typed key, then `result`;
    anything else is returned as-is. Explicit null is preserved.
    """
    if isinstance(data, str):
        return data
    if data is None:
        return None
    if isinstance(data, dict):
        if key in data:
            return data[key]
        if "result" in data:
            return data["result"]
        raise ValueError("No result in query data")
    return data


class Agent:
    """Core Agent class that orchestrates AI model and device interactions."""

    def __init__(
        self,
        interface: AbstractInterface,
        options: Optional[AgentOptions] = None,
    ):
        self.interface = interface
        self.options = options or AgentOptions()

        model_config_option = self.options.model_config
        if callable(model_config_option):  # legacy callable form
            model_config_option = model_config_option()
        self._model_config_manager: ModelConfigManager = (
            ModelConfigManager(model_config_option)
            if model_config_option
            else get_global_model_config_manager()
        )

        self._runtime_cache: Dict[str, ModelRuntime] = {}
        self._action_space: Optional[List[DeviceAction]] = None
        self._task_cache: Optional[TaskCache] = None
        self.ai_contexts: Dict[str, str] = {}

        # Execution state
        self.destroyed = False
        self.frozen_context: Optional[UIContext] = None
        self._frozen = False

        logger.info(f"Agent initialized for {self.interface.interface_type}")

    # ------------------------------------------------------------------
    # Model runtimes
    # ------------------------------------------------------------------

    def _model_config(self, intent: str) -> Dict[str, Any]:
        return self._model_config_manager.get_model_config(intent)

    def model_runtime(self, intent: str) -> ModelRuntime:
        if intent not in self._runtime_cache:
            self._runtime_cache[intent] = get_model_runtime(self._model_config(intent))
        return self._runtime_cache[intent]

    def _resolve_runtime(self, task_type: str) -> ModelRuntime:
        """Resolve the runtime for a task type with model fallback
        (upstream resolveModelForTaskType). Task types map to config intents:
        extract/boolean -> insight slot, locate/planning -> their own slots."""
        intent = "insight" if task_type in ("extract", "boolean") else task_type
        return resolve_model_for_task_type(self._model_config, intent, task_type)

    @property
    def action_space(self) -> List[DeviceAction]:
        if self._action_space is None:
            actions = build_action_space_for(self.interface.interface_type)
            self._action_space = [
                action
                for action in actions
                if action.primitive is None
                or _supports(self.interface, action.primitive)
            ]
        return self._action_space

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def set_ai_context(self, target: str, context: Optional[str]) -> None:
        """Set default context text for one API (upstream setAIContext)."""
        if target not in AGENT_AI_CONTEXT_KEYS:
            raise TypeError(f"Unknown Agent context key: {target}")
        if context is None:
            self.ai_contexts.pop(target, None)
        else:
            self.ai_contexts[target] = context

    def _resolve_call_context(self, api_name: str, options: Optional[dict]) -> Optional[str]:
        if options and options.get("context") is not None:
            return options["context"]
        if api_name in self.ai_contexts:
            return self.ai_contexts[api_name]
        return self.ai_contexts.get("default")

    async def get_ui_context(self, action: str = "locate") -> UIContext:
        if self._frozen and self.frozen_context is not None:
            return self.frozen_context
        context = await self.interface.get_context()
        if self._frozen:
            self.frozen_context = context
        return context

    async def _get_ui_context(self, action: str) -> UIContext:
        return await self.get_ui_context(action)

    async def freeze_page_context(self) -> None:
        """Freeze the current UI context; subsequent AI calls reuse it."""
        self.frozen_context = await self.get_ui_context("locate")
        self._frozen = True

    # keep the previous Python SDK name as an alias
    freeze_context = freeze_page_context

    def unfreeze_page_context(self) -> None:
        self._frozen = False
        self.frozen_context = None

    unfreeze_context = unfreeze_page_context

    def _notify_task_start(self, tip: str) -> None:
        callback: Optional[Callable] = getattr(self.options, "on_task_start_tip", None)
        if callback:
            result = callback(tip)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    # ------------------------------------------------------------------
    # aiAct: the planning loop
    # ------------------------------------------------------------------

    async def ai_act(
        self,
        task_prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Execute a task via the planning loop; returns the finalize message."""
        self._check_not_destroyed()
        opt = opt or {}
        prompt_str = user_prompt_to_string(task_prompt)

        # Effort resolution (upstream aiAct boundary)
        effort = opt.get("effort")
        deep_think = opt.get("deepThink")
        if effort and deep_think is not None:
            logger.warning(
                'When both "effort" and "deepThink" are provided, "effort" takes precedence.'
            )
        if effort is None:
            effort = "deepThink" if deep_think is True else "balance"
        planning_adapter = self.model_runtime("planning").adapter
        if effort == "fast" and planning_adapter.planning_kind == "custom":
            raise ValueError(
                'The "fast" aiAct effort is not supported with custom planning '
                f"adapters (modelFamily: {planning_adapter.family})"
            )
        if effort == "deepThink" and planning_adapter.planning_kind == "custom":
            logger.warning(
                "deepThink aiAct is not supported with custom planning adapters; "
                "downgrading to balance effort."
            )
            effort = "balance"

        deep_locate = bool(opt.get("deepLocate"))
        if deep_locate and not planning_adapter.supports_action_deep_locate:
            logger.warning(
                'The "deepLocate" option is not supported for aiAct with the '
                f"current planning adapter (modelFamily: "
                f"{planning_adapter.family}); it will be ignored."
            )
            deep_locate = False

        include_locate_in_planning = (
            effort != "deepThink"
            and self._model_config("locate").get("slot") == "default"
        )
        replanning_cycle_limit = (
            opt.get("replanningCycleLimit")
            or getattr(self.options, "replanning_cycle_limit", None)
            or _env_number("MIDSCENE_REPLANNING_CYCLE_LIMIT")
            or planning_adapter.replanning_cycle_limit
            or 20
        )

        cacheable = opt.get("cacheable", True)
        cache = self._get_task_cache()
        cached_entry = None
        report_tasks: List[Dict[str, Any]] = []
        if cache is not None and planning_adapter.cache_enabled and cacheable:
            cached_entry = cache.match_plan_cache(prompt_str)
            if cached_entry:
                replayed = False
                try:
                    replayed = await self._replay_cached_plan(
                        cached_entry, report_tasks
                    )
                except Exception as e:
                    logger.warning(f"cached plan replay failed, falling back to AI: {e}")
                if replayed:
                    cache_yaml = cached_entry.get(
                        "yamlWorkflow"
                    ) or cached_entry.get("yaml_workflow")
                    self._write_execution_report(
                        prompt_str, report_tasks, None, cache_yaml=cache_yaml
                    )
                    return None
                cache.release_plan_cache(prompt_str)
                report_tasks.clear()

        conversation_history = ConversationHistory()
        error_count = 0
        output_string: Optional[str] = None
        planning_advice: Optional[str] = None
        plan_result: Optional[Dict[str, Any]] = None
        executed_actions: List[Dict[str, Any]] = []

        context = await self._get_ui_context("aiAct")
        replan_count = 0
        report_error: Optional[BaseException] = None
        try:
            while True:
                if replan_count > replanning_cycle_limit:
                    raise RuntimeError(
                        f"Task stopped: the planning cycle limit ({replanning_cycle_limit}) "
                        "has been reached. This limit prevents the model from getting "
                        "stuck in an endless planning loop. Increase replanningCycleLimit "
                        "or set the environment variable MIDSCENE_REPLANNING_CYCLE_LIMIT."
                    )

                # Delegation forces the default planning model for this round.
                use_delegation_runtime = (
                    plan_result is not None and plan_result.get("delegation")
                )
                planning_runtime = (
                    self.model_runtime("default")
                    if use_delegation_runtime
                    else self.model_runtime("planning")
                )

                plan_result = await self._plan_once(
                    prompt_str,
                    context,
                    planning_runtime,
                    conversation_history,
                    effort=effort,
                    include_locate_in_planning=include_locate_in_planning,
                    planning_advice=planning_advice,
                    action_context=self._resolve_call_context("aiAct", opt),
                )
                planning_advice = None
                replan_count += 1

                if plan_result.get("error"):
                    raise RuntimeError(
                        f"Failed to continue: {plan_result['error']}\n{plan_result.get('log') or ''}"
                    )

                if plan_result.get("finalize_success") is not None:
                    if not plan_result["finalize_success"]:
                        raise AssertionError(
                            "Task failed: "
                            f"{plan_result.get('finalize_message') or 'No error message provided'}\n"
                            f"{plan_result.get('log') or ''}"
                        )
                    output_string = plan_result.get("finalize_message")
                    break

                action = plan_result.get("action")
                if action is None:
                    raise RuntimeError(
                        "AI planning returned no action and no completion status"
                    )

                if deep_locate:
                    for param_value in (action.get("param") or {}).values():
                        if (
                            isinstance(param_value, dict)
                            and param_value.get("prompt")
                            and "deepLocate" not in param_value
                        ):
                            param_value["deepLocate"] = True
                        elif (
                            isinstance(param_value, dict)
                            and isinstance(param_value.get("locate"), dict)
                        ):
                            param_value["locate"].setdefault("deepLocate", True)

                if action.get("type") == "Finished":
                    # Custom planners (UI-TARS) signal completion this way.
                    output_string = (action.get("thought") or "") or None
                    break

                started_at = time.time()
                try:
                    await self._execute_planning_action(action)
                    report_tasks.append(
                        self._build_action_report_task(
                            action, started_at, time.time()
                        )
                    )
                    executed_actions.append(
                        {
                            "type": action["type"],
                            **_strip_runtime_locate_result(action.get("param") or {}),
                        }
                    )
                    await asyncio.sleep(DEFAULT_WAIT_AFTER_ACTION_MS / 1000)
                    conversation_history.pending_feedback_message = (
                        "Time: "
                        f"{self._time_string()}, I have finished the action previously planned."
                    )
                except Exception as e:
                    report_tasks.append(
                        self._build_action_report_task(
                            action,
                            started_at,
                            time.time(),
                            status="failed",
                            error=e,
                        )
                    )
                    error_count += 1
                    conversation_history.pending_feedback_message = (
                        f"Time: {self._time_string()}, Error executing running tasks: "
                        f"{_truncate(str(e), 500)}"
                    )
                    logger.warning(
                        f"error when executing planned action, continuing: {e} "
                        f"(error count: {error_count})"
                    )
                    if error_count > MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP:
                        raise RuntimeError(
                            "Too many errors in one planning loop"
                        ) from e

                context = await self._get_ui_context("aiAct")
        except BaseException as e:
            report_error = e
            raise
        finally:
            self._write_execution_report(
                prompt_str, report_tasks, output_string, error=report_error
            )

        if cache is not None and not cache.read_only_mode and executed_actions:
            cache.append_plan_cache(
                prompt_str,
                pyyaml.dump(
                    {"tasks": [{"name": prompt_str, "flow": executed_actions}]},
                    allow_unicode=True,
                    sort_keys=False,
                    width=10**6,
                ).strip(),
            )

        return output_string

    async def _plan_once(
        self,
        prompt_str: str,
        context: UIContext,
        planning_runtime: ModelRuntime,
        conversation_history: ConversationHistory,
        effort: str,
        include_locate_in_planning: bool,
        planning_advice: Optional[str],
        action_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        adapter = planning_runtime.adapter
        if adapter.planning_kind == "custom" and adapter.planning_plan_fn is not None:
            return await adapter.planning_plan_fn(
                instruction=prompt_str,
                context=context,
                model_runtime=planning_runtime,
                action_space=self.action_space,
                conversation_history=conversation_history,
                include_locate_in_planning=include_locate_in_planning,
                action_context=action_context,
            )
        if adapter.family == "jev":
            return await jev_plan(
                instruction=prompt_str,
                context=context,
                model_runtime=planning_runtime,
                action_space=self.action_space,
                conversation_history=conversation_history,
                include_locate_in_planning=include_locate_in_planning,
                action_context=action_context,
            )
        return await standard_plan(
            user_instruction=prompt_str,
            context=context,
            model_runtime=planning_runtime,
            action_space=self.action_space,
            conversation_history=conversation_history,
            include_locate_in_planning=include_locate_in_planning,
            effort=effort,
            action_context=action_context,
            planning_advice=planning_advice,
            images_include_count=2 if effort == "deepThink" else 1,
        )

    async def ai_action(self, prompt: TUserPrompt, **kwargs) -> Optional[str]:
        """Deprecated alias of aiAct (upstream keeps the same alias)."""
        return await self.ai_act(prompt, kwargs or None)

    # ------------------------------------------------------------------
    # Single-action convenience APIs (locate + device action, no planning)
    # ------------------------------------------------------------------

    async def _call_action_in_action_space(
        self,
        action_type: str,
        param: Optional[Dict[str, Any]] = None,
    ) -> None:
        definition = find_action_in_action_space_or_throw(action_type, self.action_space)
        param = dict(param or {})
        tip = definition.interface_alias or action_type
        locate = param.get("locate") or param.get("from")
        if isinstance(locate, dict) and locate.get("prompt"):
            tip = f"{tip} - {locate['prompt']}"
        self._notify_task_start(tip)
        if definition.execute is None:
            raise NotImplementedError(f"Action {action_type} has no executor")
        await definition.execute(param, self.interface, self._locate_for_action)

    def _build_locate_param(
        self, prompt: TUserPrompt, opt: Dict[str, Any], api_name: str
    ) -> Dict[str, Any]:
        locate: Dict[str, Any] = {"prompt": prompt}
        deep_locate = opt.get("deepLocate", opt.get("deepThink", False))
        if deep_locate:
            locate["deepLocate"] = True
        if opt.get("cacheable") is not None:
            locate["cacheable"] = opt["cacheable"]
        return locate

    async def ai_tap(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "Tap", {"locate": self._build_locate_param(locate_prompt, opt, "aiTap")}
        )

    async def ai_right_click(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "RightClick", {"locate": self._build_locate_param(locate_prompt, opt, "aiRightClick")}
        )

    async def ai_middle_click(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "MiddleClick", {"locate": self._build_locate_param(locate_prompt, opt, "aiMiddleClick")}
        )

    async def ai_double_click(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "DoubleClick", {"locate": self._build_locate_param(locate_prompt, opt, "aiDoubleClick")}
        )

    async def ai_hover(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "Hover", {"locate": self._build_locate_param(locate_prompt, opt, "aiHover")}
        )

    async def ai_clear_input(self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._check_not_destroyed()
        await self._call_action_in_action_space(
            "ClearInput", {"locate": self._build_locate_param(locate_prompt, opt, "aiClearInput")}
        )

    async def ai_input(
        self,
        locate_prompt: Optional[Union[TUserPrompt, str, int]] = None,
        opt: Optional[Dict[str, Any]] = None,
        value: Optional[Union[str, int]] = None,
    ) -> None:
        """aiInput.

        New signature: ai_input(locate_prompt, {value, mode, ...}).
        Legacy signature: ai_input(value, locate_prompt).
        """
        self._check_not_destroyed()
        legacy_form = opt is not None and value is None and (
            not isinstance(opt, dict) or "prompt" in opt or "images" in opt
        )
        if legacy_form:
            # legacy form: ai_input(value, locate_prompt)
            value, locate_prompt, opt = locate_prompt, opt, {}
        opt = dict(opt or {})
        input_value = opt.pop("value", value)
        if input_value is None:
            raise ValueError(
                "input value must be a string or number, use empty string if you "
                "want to clear the input"
            )
        if not isinstance(input_value, (str, int)):
            raise ValueError(
                "input value must be a string or number, use empty string if you "
                "want to clear the input"
            )
        input_value = str(input_value)
        if opt.get("mode") == "append":  # backward compat
            opt["mode"] = "typeOnly"
        param: Dict[str, Any] = {"value": input_value}
        if locate_prompt is not None:
            param["locate"] = self._build_locate_param(locate_prompt, opt, "aiInput")
        if opt.get("mode"):
            param["mode"] = opt["mode"]
        await self._call_action_in_action_space("Input", param)

    async def ai_keyboard_press(
        self,
        locate_prompt: Optional[TUserPrompt] = None,
        opt: Optional[Dict[str, Any]] = None,
        key_name: Optional[str] = None,
    ) -> None:
        """aiKeyboardPress.

        New: (locate_prompt | None, {keyName}); legacy: (keyName, locate_prompt?).
        """
        self._check_not_destroyed()
        opt = dict(opt or {})
        if (
            isinstance(locate_prompt, str)
            and "keyName" not in opt
            and key_name is None
        ):
            key_name = locate_prompt
            locate_prompt = None
        key = opt.pop("keyName", key_name)
        if not key:
            raise ValueError("missing keyName for keyboard press")
        param: Dict[str, Any] = {"keyName": key}
        if locate_prompt is not None:
            param["locate"] = self._build_locate_param(locate_prompt, opt, "aiKeyboardPress")
        await self._call_action_in_action_space("KeyboardPress", param)

    async def ai_scroll(
        self,
        locate_prompt: Optional[TUserPrompt] = None,
        opt: Optional[Dict[str, Any]] = None,
        scroll_param: Optional[Union[Dict[str, Any], ScrollParam]] = None,
    ) -> None:
        """aiScroll.

        New: (locate_prompt | None, {direction, scrollType, distance});
        legacy: (scroll_param, locate_prompt?).
        """
        self._check_not_destroyed()
        if opt is not None and not isinstance(opt, dict):
            # legacy form: ai_scroll(scroll_param, locate_prompt)
            locate_prompt, scroll_param, opt = opt, scroll_param or locate_prompt, {}
        opt = dict(opt or {})
        if isinstance(locate_prompt, (dict, ScrollParam)):
            scroll_param = locate_prompt
            locate_prompt = None
        if scroll_param is not None:
            if isinstance(scroll_param, ScrollParam):
                scroll_param = {
                    "direction": scroll_param.direction,
                    "scrollType": scroll_param.scroll_type,
                    "distance": scroll_param.distance,
                }
            opt.update({k: v for k, v in scroll_param.items() if v is not None})
        param: Dict[str, Any] = {
            "direction": opt.get("direction") or "down",
            "scrollType": opt.get("scrollType") or "singleAction",
        }
        if opt.get("distance") is not None:
            param["distance"] = opt["distance"]
        if locate_prompt is not None:
            param["locate"] = self._build_locate_param(locate_prompt, opt, "aiScroll")
        await self._call_action_in_action_space("Scroll", param)

    async def ai_long_press(
        self, locate_prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None
    ) -> None:
        self._check_not_destroyed()
        opt = dict(opt or {})
        param: Dict[str, Any] = {
            "locate": self._build_locate_param(locate_prompt, opt, "aiLongPress")
        }
        if opt.get("duration") is not None:
            param["duration"] = opt["duration"]
        await self._call_action_in_action_space("LongPress", param)

    async def ai_drag_and_drop(
        self,
        from_prompt: TUserPrompt,
        to_prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._check_not_destroyed()
        opt = dict(opt or {})
        param: Dict[str, Any] = {
            "from": self._build_locate_param(from_prompt, opt, "aiDragAndDrop"),
            "to": self._build_locate_param(to_prompt, opt, "aiDragAndDrop"),
        }
        await self._call_action_in_action_space("DragAndDrop", param)

    async def sleep(self, ms: int, options: Optional[Dict[str, Any]] = None) -> None:
        """Wait for ms milliseconds; no model call (upstream agent.sleep)."""
        if not isinstance(ms, (int, float)) or ms <= 0:
            raise ValueError("ms for sleep must be a finite number greater than 0")
        self._notify_task_start("Sleep")
        await asyncio.sleep(ms / 1000)

    # ------------------------------------------------------------------
    # Insight APIs (aiQuery/aiBoolean/aiNumber/aiString/aiAsk/aiAssert/aiWaitFor)
    # ------------------------------------------------------------------

    async def ai_query(
        self,
        demand: Union[str, Dict[str, str]],
        opt: Optional[Dict[str, Any]] = None,
    ) -> Any:
        self._check_not_destroyed()
        opt = opt or {}
        context = await self._get_ui_context("aiQuery")
        runtime = self._resolve_runtime(TASK_TYPE_EXTRACT)
        response = await ai_extract_element_info(
            task_type="extract",
            data_query=demand,
            context=context,
            model_runtime=runtime,
            page_description="",
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._resolve_call_context("aiQuery", opt),
        )
        return response.get("parse_result", {}).get("data")

    async def ai_extract(
        self,
        prompt: Union[str, Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Deprecated alias of ai_query (previous Python SDK name)."""
        return await self.ai_query(prompt, options)

    async def ai_boolean(self, prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> bool:
        return await self._query_primitive("Boolean", "aiBoolean", prompt, opt)

    async def ai_number(self, prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None):
        return await self._query_primitive("Number", "aiNumber", prompt, opt)

    async def ai_string(self, prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> str:
        return await self._query_primitive("String", "aiString", prompt, opt)

    async def ai_ask(self, prompt: TUserPrompt, opt: Optional[Dict[str, Any]] = None) -> str:
        return await self._query_primitive("String", "aiAsk", prompt, opt)

    async def _query_primitive(
        self,
        demand_type: str,
        api_name: str,
        prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Any:
        opt = opt or {}
        context = await self._get_ui_context(api_name)
        runtime = self._resolve_runtime(
            TASK_TYPE_BOOLEAN if demand_type == "Boolean" else TASK_TYPE_EXTRACT
        )
        from .ai_model.prompts.insight import build_type_query_demand_value

        demand_value = build_type_query_demand_value(
            demand_type, user_prompt_to_string(prompt)
        )
        # Upstream keys typed queries by the demand type (Boolean/Number/String).
        response = await ai_extract_element_info(
            task_type="extract",
            data_query={demand_type: demand_value},
            context=context,
            model_runtime=runtime,
            page_description="",
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._resolve_call_context(api_name, opt),
        )
        data = response.get("parse_result", {}).get("data")
        return _extract_typed_query_result(data, demand_type)

    async def ai_assert(
        self,
        assertion: TUserPrompt,
        message: Optional[str] = None,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """aiAssert; with keepRawResponse returns {pass, thought, message}."""
        self._check_not_destroyed()
        opt = dict(opt or {})
        context = await self._get_ui_context("aiAssert")
        runtime = self._resolve_runtime(TASK_TYPE_BOOLEAN)
        assertion_text = user_prompt_to_string(assertion)
        from .ai_model.prompts.insight import build_type_query_demand_value

        response = await ai_extract_element_info(
            task_type="boolean",
            data_query={
                "StatementIsTruthy": build_type_query_demand_value(
                    "Assert", assertion_text
                )
            },
            context=context,
            model_runtime=runtime,
            page_description="",
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._resolve_call_context("aiAssert", opt),
        )
        parse_result = response.get("parse_result", {})
        data = parse_result.get("data")
        passed = bool(_extract_typed_query_result(data, "StatementIsTruthy"))
        thought = parse_result.get("thought") or ""

        if opt.get("keepRawResponse"):
            failure_message = (
                None
                if passed
                else (
                    f"Assertion failed: {message or assertion_text}\n"
                    f"Reason: {thought or '(no_reason)'}"
                )
            )
            return {"pass": passed, "thought": thought, "message": failure_message}
        if not passed:
            raise AssertionError(
                f"Assertion failed: {message or assertion_text}\n"
                f"Reason: {thought or '(no_reason)'}"
            )
        return None

    async def ai_wait_for(
        self,
        assertion: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._check_not_destroyed()
        opt = opt or {}
        timeout_ms = opt.get("timeoutMs", opt.get("timeout", 15000))
        check_interval_ms = opt.get("checkIntervalMs", 3000)
        if check_interval_ms > timeout_ms:
            raise ValueError(
                "wrong config for waitFor: checkIntervalMs should be less than or "
                f"equal to timeoutMs, got {check_interval_ms} > {timeout_ms}"
            )
        start = time.time()
        while True:
            context = await self._get_ui_context("aiWaitFor")
            runtime = self._resolve_runtime(TASK_TYPE_BOOLEAN)
            from .ai_model.prompts.insight import build_type_query_demand_value

            response = await ai_extract_element_info(
                task_type="boolean",
                data_query={
                    "StatementIsTruthy": build_type_query_demand_value(
                        "WaitFor", user_prompt_to_string(assertion)
                    )
                },
                context=context,
                model_runtime=runtime,
                page_description="",
                screenshot_included=opt.get("screenshotIncluded", True),
                context_text=self._resolve_call_context("aiWaitFor", opt),
            )
            data = response.get("parse_result", {}).get("data")
            # A missing key or null means "not true yet" for waitFor.
            passed = bool(
                data.get("StatementIsTruthy")
                if isinstance(data, dict)
                else data
            )
            if passed:
                return
            if (time.time() - start) * 1000 >= timeout_ms:
                raise TimeoutError(f"waitFor timeout: {user_prompt_to_string(assertion)}")
            await asyncio.sleep(check_interval_ms / 1000)

    async def ai_locate(
        self,
        prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> LocateResult:
        """aiLocate; returns {center, rect, description}."""
        self._check_not_destroyed()
        opt = opt or {}
        context = await self._get_ui_context("aiLocate")
        element = await self._run_locate(
            prompt,
            context,
            deep_locate=bool(opt.get("deepLocate", opt.get("deepThink", False))),
        )
        return LocateResult(
            center=list(element["center"]),
            rect=element.get("rect"),
            description=element.get("description"),
        )

    # ------------------------------------------------------------------
    # Direct device operations
    # ------------------------------------------------------------------

    async def tap(self, x: float, y: float) -> None:
        self._check_not_destroyed()
        await self.interface.tap(x, y)

    async def input_text(self, text: str) -> None:
        self._check_not_destroyed()
        await self.interface.input_text(text)

    async def keyboard_press(self, key: str) -> None:
        self._check_not_destroyed()
        await self.interface.keyboard_press(key)

    async def scroll(
        self, params: Union[ScrollParam, str], distance: Optional[int] = None
    ) -> None:
        self._check_not_destroyed()
        if isinstance(params, ScrollParam):
            await self.interface.scroll(params.direction, params.distance)
        else:
            await self.interface.scroll(params, distance)

    async def get_context(self) -> UIContext:
        self._check_not_destroyed()
        return await self._get_ui_context("manual")

    async def destroy(self) -> None:
        if not self.destroyed:
            logger.info("Destroying agent")
            self.destroyed = True
            if self._task_cache:
                self._task_cache.flush()

    def flush_cache(self, options: Optional[Dict[str, Any]] = None) -> None:
        if self._task_cache is None:
            raise RuntimeError("Cache is not configured")
        self._task_cache.flush()

    async def run_yaml(
        self, yaml_script_content: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run a YAML automation script (upstream agent.runYaml)."""
        from .yaml_runner import ScriptPlayer, parse_yaml_script

        if self.destroyed:
            raise RuntimeError("Cannot run YAML using a destroyed Agent.")
        script = parse_yaml_script(yaml_script_content)
        player = ScriptPlayer(script, agent=self)
        await player.run()
        if player.status == "error":
            errors = [f"task - {t['name']}: {t.get('error')}" for t in player.failed_tasks]
            raise RuntimeError("Error(s) in running yaml script:\n" + "\n".join(errors))
        return {"result": player.result}

    # ------------------------------------------------------------------
    # Planning action execution + locate
    # ------------------------------------------------------------------

    async def _locate_for_action(self, locate_param: Any) -> Dict[str, Any]:
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
        cache = self._get_task_cache()
        deep_locate = bool(locate_param.get("deepLocate"))

        cached_pixel = locate_param.get("locatedPixelResult")
        # Upstream task-builder: elementFromPlan = locateParam.deepLocate
        # ? undefined : planLocatedElement. With deepLocate the plan
        # coordinates are only a search-area hint for the two-stage locate.
        if cached_pixel and cached_pixel.get("center") and not deep_locate:
            # Fresh plan coordinates take precedence over the cache. Record the
            # feature once for future runs, unless an entry already exists.
            if not (cache is not None and cache.has_locate_cache(prompt_str)):
                await self._write_locate_cache(
                    prompt_str, cached_pixel, cache, cacheable, None
                )
            return cached_pixel

        replace_index: Optional[int] = None
        if (
            cache is not None
            and cacheable is not False
            and supports_interface_extension(
                self.interface, "rect_matches_cache_feature"
            )
        ):
            matched = cache.match_locate_cache(prompt_str)
            if matched is not None:
                rect = await self._rect_from_cache_feature(matched["cache"])
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

        context = await self._get_ui_context("locate")
        element = await self._run_locate(
            prompt,
            context,
            deep_locate=deep_locate,
            plan_located_element=cached_pixel if deep_locate else None,
        )
        await self._write_locate_cache(
            prompt_str, element, cache, cacheable, replace_index
        )
        return element

    async def _rect_from_cache_feature(self, feature: Dict[str, Any]):
        try:
            return await self.interface.rect_matches_cache_feature(feature)
        except NotImplementedError:
            return None
        except Exception as e:
            logger.warning(f"Failed to resolve locate cache feature: {e}")
            return None

    async def _write_locate_cache(
        self,
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
                self.interface, "cache_feature_for_point"
            )
        ):
            return
        center = element.get("center") if isinstance(element, dict) else None
        if not center:
            return
        options: Dict[str, Any] = {"target_description": prompt_str}
        try:
            # Upstream AiJudgeOrderSensitive always uses the default slot.
            options["model_runtime"] = self.model_runtime("default")
        except Exception as e:
            # Without a runtime the interface falls back to order-insensitive paths.
            logger.debug(f"order-sensitive judge unavailable: {e}")
        try:
            feature = await self.interface.cache_feature_for_point(
                [float(center[0]), float(center[1])], options
            )
        except NotImplementedError:
            return
        except Exception as e:
            logger.warning(f"Failed to build locate cache feature: {e}")
            return
        if isinstance(feature, dict) and feature.get("xpaths"):
            cache.append_locate_cache(prompt_str, feature, replace_index)

    async def _run_locate(
        self,
        prompt: TUserPrompt,
        context: UIContext,
        deep_locate: bool = False,
        plan_located_element: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime = self._resolve_runtime(TASK_TYPE_LOCATE)
        if runtime.adapter.locate_kind == "custom" and runtime.adapter.locate_fn is not None:
            response = await runtime.adapter.locate_fn(
                target_element_description=prompt,
                locate_image={
                    "imageBase64": context.screenshot_base64,
                    "width": context.size.width,
                    "height": context.size.height,
                },
                model_runtime=runtime,
            )
            located = response.get("locatedPixelResult")
            if located and located.get("center"):
                return {
                    "center": list(located["center"]),
                    "rect": located.get("rect"),
                    "description": user_prompt_to_string(prompt),
                }
            errors = response.get("errors") or ["element not found"]
            raise LocateFailureError(
                f"Element not found : {user_prompt_to_string(prompt)}"
                + (f" ({'; '.join(errors)})" if errors else "")
            )
        response = await locate_service(
            query_prompt=prompt,
            context=context,
            model_runtime=self._resolve_runtime(TASK_TYPE_LOCATE),
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
        return element

    async def _execute_planning_action(self, action: Dict[str, Any]) -> None:
        action_type = action.get("type")
        definition = find_action_in_action_space_or_throw(action_type, self.action_space)
        param = action.get("param") or {}
        if definition.execute is None:
            raise NotImplementedError(f"Action {action_type} has no executor")
        logger.info(f"Executing action {action_type}: {param}")
        await definition.execute(param, self.interface, self._locate_for_action)

    async def _replay_cached_plan(
        self,
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
            await self._execute_planning_action(action)
            if reported is not None:
                reported.append(
                    self._build_action_report_task(
                        action, started_at, time.time()
                    )
                )
        logger.info("Cached plan replay completed")
        return True

    # -- execution report ---------------------------------------------------

    @staticmethod
    def _build_action_report_task(
        action: Dict[str, Any],
        started_at: float,
        finished_at: float,
        status: str = "finished",
        error: Optional[BaseException] = None,
    ) -> Dict[str, Any]:
        task = build_execution_task(
            "Action Space",
            action.get("type"),
            _strip_runtime_locate_result(action.get("param") or {}),
            status=status,
            timing={
                "start": int(started_at * 1000),
                "end": int(finished_at * 1000),
                "cost": int((finished_at - started_at) * 1000),
            },
        )
        if error is not None:
            task["errorMessage"] = str(error)
        return task

    def _write_execution_report(
        self,
        prompt_str: str,
        action_tasks: List[Dict[str, Any]],
        output: Optional[str],
        error: Optional[BaseException] = None,
        cache_yaml: Optional[str] = None,
    ) -> Optional[str]:
        """Persist the upstream-shaped execution dump for one aiAct run."""
        if not getattr(self.options, "generate_report", True):
            return None
        try:
            if cache_yaml is not None:
                # Matches upstream loadYamlFlowAsPlanning task metadata.
                planning_task = build_execution_task(
                    "Planning",
                    "LoadYaml",
                    {"userInstruction": prompt_str},
                    status="finished",
                    output={
                        "actions": [],
                        "shouldContinuePlanning": False,
                        "log": "",
                        "yamlString": cache_yaml,
                    },
                    hitBy={"from": "Cache", "context": {"yamlString": cache_yaml}},
                )
            else:
                planning_task = build_execution_task(
                    "Planning",
                    "Plan",
                    {"userInstruction": prompt_str},
                    status="failed" if error is not None else "finished",
                    output=output,
                )
                if error is not None:
                    planning_task["errorMessage"] = str(error)
            tag = getattr(self.interface_type, "value", self.interface_type)
            name = getattr(self.options, "report_file_name", None)
            if name:
                name = os.path.basename(name)
                if name.lower().endswith((".json", ".html")):
                    name = name.rsplit(".", 1)[0]
            else:
                name = get_report_file_name(tag)
            builder = ExecutionDumpBuilder(
                group_name=getattr(self.options, "group_name", "Midscene Report"),
                group_description=getattr(
                    self.options, "group_description", ""
                ),
                device_type=tag,
            )
            builder.add_execution(prompt_str, [planning_task, *action_tasks])
            return builder.write_to_disk(name)
        except Exception as e:
            logger.warning(f"Failed to write execution report: {e}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_task_cache(self) -> Optional[TaskCache]:
        cache_id = getattr(self.options, "cache_id", None)
        if not is_cache_enabled() and not cache_id:
            return None
        if self._task_cache is None:
            self._task_cache = TaskCache(
                cache_id=cache_id or "midscene-python", enabled=True
            )
        return self._task_cache

    def _check_not_destroyed(self) -> None:
        if self.destroyed:
            raise RuntimeError("Agent has been destroyed")

    @staticmethod
    def _time_string() -> str:
        return time.strftime("%H:%M:%S")

    @property
    def interface_type(self) -> InterfaceType:
        return self.interface.interface_type
