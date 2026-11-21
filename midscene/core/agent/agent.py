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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import yaml as pyyaml
from loguru import logger

from midscene.core.device import (
    DeviceAction,
    _supports,
    build_action_space_for,
    find_action_in_action_space_or_throw,
)
from midscene.core.ai_model.models import ModelRuntime, get_model_runtime, resolve_model_for_task_type
from midscene.shared.env import (
    ModelConfigManager,
    get_global_model_config_manager,
)
from midscene.core.ai_model.workflows import (
    ConversationHistory,
    ai_extract_element_info,
    standard_plan,
)
from midscene.core.ai_model.shared.multimodal_prompt import user_prompt_to_string
from midscene.core.ai_model.models.jev.planning import jev_plan
from midscene.core.agent import (
    cache_config,
    observe_node,
    progress,
    record_to_report as record_to_report_module,
    report_file_name,
    report_manager,
    screenshot_preparation,
    task_builder,
    ui_utils,
)
from midscene.core.agent.usage_intent import intent_for_task_type
from midscene.core.agent.common import (
    AGENT_AI_CONTEXT_KEYS,
    BROWSER_NAVIGATION_ERROR_PATTERN,
    MAX_ERROR_COUNT_IN_ONE_PLANNING_LOOP,
    TASK_TYPE_BOOLEAN,
    TASK_TYPE_EXTRACT,
)
from midscene.core.agent.agent_options import AgentOptions
from midscene.core.agent.action_readiness import wait_for_action_ready
from midscene.core.agent.metrics import record_usage_metrics
from midscene.core.agent.tasks import (
    action_progress_summary,
    build_action_report_task,
)
from midscene.core.agent.task_cache import TaskCache
from midscene.core.dump import ExecutionDumpBuilder, build_execution_task, get_report_file_name
from midscene.core.types import (
    AbstractInterface,
    InterfaceType,
    LocateResult,
    ScrollParam,
    TUserPrompt,
    UIContext,
)

from midscene.core.agent.file_chooser import (
    _FILE_CHOOSER_ACCEPT_KEYS,
    _FILE_CHOOSER_ALLOWED_DIR_KEYS,
    _FileChooserAccepter,
    _normalize_file_paths,
    _with_file_chooser,
)
from midscene.core.agent import run_markdown as run_markdown_module
from midscene.core.agent.run_markdown import _reference_images_from_prompt
from midscene.core.agent.utils import (
    _env_number,
    _extract_typed_query_result,
    _get_opt,
    _strip_runtime_locate_result,
    _throw_if_aborted,
    _truncate,
)


_ABORT_SIGNAL_KEYS = ("abortSignal", "abort_signal")


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
        self.ai_contexts: Dict[str, str] = dict(
            getattr(self.options, "ai_contexts", None) or {}
        )
        legacy_action_context = getattr(self.options, "ai_action_context", None)
        if legacy_action_context and "aiAct" not in self.ai_contexts:
            self.ai_contexts["aiAct"] = legacy_action_context
        self._report_builder = None
        self._usage_by_intent: Dict[str, Dict[str, int]] = {}
        # Report state shared by the upstream-shaped public APIs
        # (resetDump/finalizeReport/dumpDataString/reportHTMLString).
        self._dump_update_listeners: List[Callable] = []
        self._progress_listeners: List[Callable] = []
        self._progress_sequence = 0
        self._report_finalized: Optional[str] = None
        self._report_file_name: Optional[str] = None
        self._report_artifact_store: Optional[Any] = None
        self._last_execution: Optional[Dict[str, Any]] = None
        self._execution_index_by_runner: Dict[int, int] = {}
        # File chooser state for the running aiAct (upstream
        # activeFileChooserAccepter / activeFileChooserAllowedDir).
        self._active_file_chooser_accepter: Optional[_FileChooserAccepter] = None
        self._active_file_chooser_allowed_dir: Optional[str] = None

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
            runtime = get_model_runtime(self._model_config(intent))
            on_llm_usage = getattr(self.options, "on_llm_usage", None)
            if on_llm_usage:
                runtime.on_usage = on_llm_usage
            self._runtime_cache[intent] = runtime
        return self._runtime_cache[intent]

    @property
    def metrics(self) -> Dict[str, Dict[str, int]]:
        """Accumulated token usage per model-config intent (upstream metrics)."""
        return self._usage_by_intent

    def _record_usage_metrics(self, intent: str, usage: Optional[Dict[str, Any]]) -> None:
        record_usage_metrics(self._usage_by_intent, intent, usage)

    def _resolve_runtime(self, task_type: str) -> ModelRuntime:
        """Resolve the runtime for a task type with model fallback."""
        return resolve_model_for_task_type(
            self._model_config, intent_for_task_type(task_type), task_type
        )

    @property
    def action_space(self) -> List[DeviceAction]:
        if self._action_space is None:
            actions = list(build_action_space_for(self.interface.interface_type))
            if _supports(self.interface, "register_file_chooser_listener"):
                actions.append(self._build_file_chooser_action())
            self._action_space = [
                action
                for action in actions
                if action.primitive is None
                or _supports(self.interface, action.primitive)
            ]
        return self._action_space

    async def get_action_space(self) -> List[DeviceAction]:
        """Return the full device action space for this agent
        (upstream `agent.getActionSpace()`).

        The sync spelling is the `action_space` property; this async method
        exists only for upstream API parity and returns the same live list
        the planning/dispatch path consumes — treat it as read-only."""
        return self.action_space

    def _build_file_chooser_action(self) -> DeviceAction:
        """File-chooser action only exposed when the interface implements the
        listener (upstream defineActionRegisterFileChooserAccept)."""

        async def execute(param: Dict[str, Any], device: Any, locate_fn) -> None:
            accepter = self._active_file_chooser_accepter
            if accepter is None:
                raise RuntimeError(
                    "RegisterFileChooserAccept can only be used while aiAct "
                    "is running"
                )
            allowed_dir = self._active_file_chooser_allowed_dir
            if not allowed_dir:
                raise RuntimeError(
                    "RegisterFileChooserAccept requires aiAct option "
                    "fileChooserAllowedDir"
                )
            await accepter.register_from_allowed_dir(param.get("files"), allowed_dir)

        return DeviceAction(
            name="RegisterFileChooserAccept",
            description=(
                "Configure files for file chooser dialogs triggered by later "
                "actions in this aiAct"
            ),
            param_schema={
                "files": {
                    "type": "string | string[]",
                    "description": (
                        "File path(s) within the current aiAct call's "
                        "fileChooserAllowedDir to use whenever a later action "
                        "triggers a file chooser. fileChooserAllowedDir must be "
                        "provided for this action. This setting replaces any "
                        "previously registered file path(s)."
                    ),
                }
            },
            locate_fields=[],
            sample={"files": ["fixtures/document.pdf"]},
            interface_alias="registerFileChooserAccept",
            execute=execute,
        )

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

    def is_retryable_context_error(self, error: BaseException) -> bool:
        """Override in subclasses to mark transient context errors retryable.

        The base implementation retries browser-navigation races for web
        interfaces (upstream WebAgentCore subclass override).
        """
        if self.interface_type == InterfaceType.WEB:
            return bool(
                BROWSER_NAVIGATION_ERROR_PATTERN.search(str(error) or "")
            )
        return False


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

    def _merge_call_context(
        self,
        api_name: str,
        opt: Optional[Dict[str, Any]],
        context: UIContext,
        dom_included: Union[bool, str] = False,
    ) -> Optional[str]:
        """Combine the per-API context text with the rendered DOM context
        (upstream renderAIContext, enabled by domIncluded)."""
        parts = []
        base_context = self._resolve_call_context(api_name, opt)
        if base_context:
            parts.append(base_context)
        if dom_included:
            from midscene.core.agent.prompt_context import render_ai_context

            rendered = render_ai_context(context)
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts) if parts else None

    async def _wait_for_action_ready(self, action: Dict[str, Any]) -> None:
        await wait_for_action_ready(self.options, action)

    def _notify_task_start(self, tip: str) -> None:
        callback: Optional[Callable] = getattr(self.options, "on_task_start_tip", None)
        if callback:
            result = callback(tip)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    # ------------------------------------------------------------------
    # Progress bus (upstream addProgressListener / AgentProgressEvent)
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # aiAct: the planning loop
    # ------------------------------------------------------------------

    async def ai_act(
        self,
        task_prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Execute a task via the planning loop within a file-chooser scope
        (upstream executeAiAct + FileChooserAccepter lifecycle)."""
        self._check_not_destroyed()
        opt = opt or {}
        _throw_if_aborted(_get_opt(opt, _ABORT_SIGNAL_KEYS, None))

        file_chooser_files = _get_opt(opt, _FILE_CHOOSER_ACCEPT_KEYS, None)
        normalized_files = (
            _normalize_file_paths(file_chooser_files)
            if file_chooser_files
            else None
        )
        allowed_dir = _get_opt(opt, _FILE_CHOOSER_ALLOWED_DIR_KEYS, None)

        accepter = None
        if _supports(self.interface, "register_file_chooser_listener"):
            accepter = _FileChooserAccepter(self.interface)
        self._active_file_chooser_accepter = accepter
        self._active_file_chooser_allowed_dir = (
            str(Path(allowed_dir).expanduser().resolve()) if allowed_dir else None
        )

        ai_act_error: Optional[BaseException] = None
        file_chooser_error: Optional[BaseException] = None
        result: Optional[str] = None
        try:
            if normalized_files:
                if accepter is None:
                    raise RuntimeError(
                        "File upload is not supported on "
                        f"{self.interface.interface_type}"
                    )
                await accepter.register(normalized_files)
            result = await self._ai_act_impl(task_prompt, opt)
        except BaseException as e:
            ai_act_error = e
        finally:
            self._active_file_chooser_accepter = None
            self._active_file_chooser_allowed_dir = None
            if accepter is not None:
                try:
                    file_chooser_error = await accepter.clear()
                except BaseException as e:
                    logger.warning(
                        f"Failed to clear file chooser registration: {e}"
                    )

        if ai_act_error is not None:
            raise ai_act_error
        if file_chooser_error is not None:
            raise file_chooser_error
        return result

    async def _ai_act_impl(
        self,
        task_prompt: TUserPrompt,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Execute a task via the planning loop; returns the finalize message."""
        self._check_not_destroyed()
        opt = opt or {}
        abort_signal = _get_opt(opt, _ABORT_SIGNAL_KEYS, None)
        _throw_if_aborted(abort_signal)
        prompt_str = user_prompt_to_string(task_prompt)
        await self._emit_progress("aiAct", "start", {"prompt": prompt_str})

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
        reference_images = await _reference_images_from_prompt(
            task_prompt, force_base64=planning_adapter.family == "jev"
        )
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
        # Without planning-cache support the action sequence may change between
        # runs, so locate caching is disabled for the whole aiAct (upstream #3418).
        ai_act_cacheable = cacheable if planning_adapter.cache_enabled else False
        cache = self._get_task_cache()
        cached_entry = None
        report_tasks: List[Dict[str, Any]] = []
        if cache is not None and ai_act_cacheable:
            cached_entry = cache.match_plan_cache(prompt_str)
            if cached_entry:
                replayed = False
                try:
                    replayed = await self._replay_cached_plan(
                        cached_entry, report_tasks
                    )
                except Exception as e:
                    _throw_if_aborted(abort_signal)
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
                _throw_if_aborted(abort_signal)
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

                await self._emit_progress(
                    "aiAct",
                    "plan_thinking",
                    {
                        "prompt": prompt_str,
                        "planIndex": replan_count + 1,
                        "planLimit": replanning_cycle_limit,
                        "screenshot": context.screenshot_base64,
                    },
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
                    reference_images=reference_images,
                )
                planning_advice = None
                replan_count += 1

                if plan_result.get("error"):
                    await self._emit_progress(
                        "aiAct",
                        "plan_failed",
                        {
                            "prompt": prompt_str,
                            "error": str(plan_result["error"]),
                            "log": plan_result.get("log"),
                        },
                    )
                    raise RuntimeError(
                        f"Failed to continue: {plan_result['error']}\n{plan_result.get('log') or ''}"
                    )

                if plan_result.get("finalize_success") is not None:
                    if not plan_result["finalize_success"]:
                        await self._emit_progress(
                            "aiAct",
                            "plan_failed",
                            {
                                "prompt": prompt_str,
                                "error": str(plan_result.get("finalize_message") or ""),
                                "log": plan_result.get("log"),
                            },
                        )
                        raise AssertionError(
                            "Task failed: "
                            f"{plan_result.get('finalize_message') or 'No error message provided'}\n"
                            f"{plan_result.get('log') or ''}"
                        )
                    output_string = plan_result.get("finalize_message")
                    break

                action = plan_result.get("action")
                if action is None:
                    await self._emit_progress(
                        "aiAct",
                        "plan_failed",
                        {"prompt": prompt_str, "error": "no action in plan"},
                    )
                    raise RuntimeError(
                        "AI planning returned no action and no completion status"
                    )
                await self._emit_progress(
                    "aiAct",
                    "plan_planned",
                    {
                        "prompt": prompt_str,
                        "planIndex": replan_count,
                        "planLimit": replanning_cycle_limit,
                        "action": action_progress_summary(action),
                        "thought": plan_result.get("thought"),
                        "log": plan_result.get("log"),
                    },
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
                await self._emit_progress(
                    "aiAct",
                    "action_running",
                    {
                        "prompt": prompt_str,
                        "action": action_progress_summary(action),
                    },
                )
                try:
                    _throw_if_aborted(abort_signal)
                    await self._execute_planning_action(
                        action,
                        getattr(context, "shrunk_shot_to_logical_ratio", 1.0),
                        cacheable=ai_act_cacheable,
                    )
                    report_tasks.append(
                        build_action_report_task(
                            action, started_at, time.time()
                        )
                    )
                    executed_actions.append(
                        {
                            "type": action["type"],
                            **_strip_runtime_locate_result(action.get("param") or {}),
                        }
                    )
                    await asyncio.sleep(
                        getattr(self.options, "wait_after_action_ms", 300) / 1000
                    )
                    await self._wait_for_action_ready(action)
                    await self._emit_progress(
                        "aiAct",
                        "action_done",
                        {
                            "prompt": prompt_str,
                            "action": action_progress_summary(action),
                            "durationMs": int((time.time() - started_at) * 1000),
                        },
                    )
                    time_string = await self._time_string()
                    conversation_history.pending_feedback_message = (
                        "Time: "
                        f"{time_string}, I have finished the action previously planned."
                    )
                except Exception as e:
                    _throw_if_aborted(abort_signal)
                    report_tasks.append(
                        build_action_report_task(
                            action,
                            started_at,
                            time.time(),
                            status="failed",
                            error=e,
                        )
                    )
                    await self._emit_progress(
                        "aiAct",
                        "action_failed",
                        {
                            "prompt": prompt_str,
                            "action": action_progress_summary(action),
                            "durationMs": int((time.time() - started_at) * 1000),
                            "error": str(e),
                        },
                    )
                    error_count += 1
                    time_string = await self._time_string()
                    conversation_history.pending_feedback_message = (
                        f"Time: {time_string}, Error executing running tasks: "
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
            await self._emit_progress(
                "aiAct", "failed", {"prompt": prompt_str, "error": str(e)}
            )
            raise
        finally:
            self._write_execution_report(
                prompt_str, report_tasks, output_string, error=report_error
            )

        await self._emit_progress(
            "aiAct",
            "complete",
            {"prompt": prompt_str, "output": output_string},
        )

        if cache is not None and not cache.read_only_mode and executed_actions and ai_act_cacheable:
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
        reference_images: Optional[List[str]] = None,
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
                reference_images=reference_images,
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
                reference_images=reference_images,
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
            reference_images=reference_images,
            images_include_count=2 if effort == "deepThink" else 1,
        )

    async def ai(self, *args, **kwargs) -> Optional[str]:
        """Alias of aiAct (upstream `agent.ai(...)`)."""
        return await self.ai_act(*args, **kwargs)

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
    ) -> Any:
        definition = find_action_in_action_space_or_throw(action_type, self.action_space)
        param = dict(param or {})
        tip = definition.interface_alias or action_type
        locate = param.get("locate") or param.get("from")
        if isinstance(locate, dict) and locate.get("prompt"):
            tip = f"{tip} - {locate['prompt']}"
        self._notify_task_start(tip)
        if definition.execute is None:
            raise NotImplementedError(f"Action {action_type} has no executor")
        return await definition.execute(param, self.interface, self._locate_for_action)

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
        file_chooser_files = _get_opt(opt, _FILE_CHOOSER_ACCEPT_KEYS, None)
        normalized_files = (
            _normalize_file_paths(file_chooser_files)
            if file_chooser_files
            else None
        )
        locate_param = self._build_locate_param(locate_prompt, opt, "aiTap")

        async def action() -> None:
            await self._call_action_in_action_space("Tap", {"locate": locate_param})

        await _with_file_chooser(self.interface, normalized_files, action)

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

    async def ai_pinch(
        self,
        locate_prompt: Optional[TUserPrompt],
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """aiPinch: two-finger zoom ('in' | 'out') around the element."""
        self._check_not_destroyed()
        opt = dict(opt or {})
        param: Dict[str, Any] = {"direction": opt.get("direction") or "in"}
        if locate_prompt is not None:
            param["locate"] = self._build_locate_param(locate_prompt, opt, "aiPinch")
        if opt.get("distance") is not None:
            param["distance"] = opt["distance"]
        if opt.get("duration") is not None:
            param["duration"] = opt["duration"]
        await self._call_action_in_action_space("Pinch", param)

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
            context_text=self._merge_call_context(
                "aiQuery", opt, context, opt.get("domIncluded", False)
            ),
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
        from midscene.core.ai_model.prompt.insight import build_type_query_demand_value

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
            context_text=self._merge_call_context(
                api_name, opt, context, opt.get("domIncluded", False)
            ),
        )
        self._record_usage_metrics("insight", response.get("usage"))
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
        from midscene.core.ai_model.prompt.insight import build_type_query_demand_value

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
            context_text=self._merge_call_context(
                "aiAssert", opt, context, opt.get("domIncluded", False)
            ),
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
            from midscene.core.ai_model.prompt.insight import build_type_query_demand_value

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
            await self.flush_report()
            if self._report_artifact_store is not None:
                try:
                    self._report_artifact_store.finalize()
                except Exception as error:  # never block interface teardown
                    logger.warning(f"Failed to finalize report artifact: {error}")
            # Not every interface owns a transport; those that do (WDA session,
            # browser context) release it here.
            interface_destroy = getattr(self.interface, "destroy", None)
            if asyncio.iscoroutinefunction(interface_destroy):
                await interface_destroy()


    # deprecated alias (upstream logScreenshot)


    async def set_ai_action_context(self, prompt: str) -> None:
        """Deprecated upstream alias for setAIContext('aiAct', ...)."""
        self.set_ai_context("aiAct", prompt)

    async def set_ai_act_context(self, prompt: str) -> None:
        """Deprecated upstream alias for setAIContext('aiAct', ...)."""
        self.set_ai_context("aiAct", prompt)


    # ------------------------------------------------------------------
    # Report APIs (upstream resetDump / finalizeReport / dumpDataString ...)
    # ------------------------------------------------------------------


    async def evaluate_javascript(self, script: str) -> Any:
        """Evaluate JavaScript through the interface (upstream evaluateJavaScript)."""
        self._check_not_destroyed()
        for method_name in (
            "evaluate_javascript",
            "evaluate_script",
            "execute_script",
        ):
            method = getattr(self.interface, method_name, None)
            if callable(method):
                result = method(script)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
        raise NotImplementedError(
            "evaluateJavaScript is not supported in current agent"
        )


    def flush_cache(self, options: Optional[Dict[str, Any]] = None) -> None:
        if self._task_cache is None:
            raise RuntimeError("Cache is not configured")
        self._task_cache.flush()


    async def run_gherkin_scenario(
        self,
        scenario_text: str,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run a Gherkin scenario: Given/When -> aiAct, Then -> aiAssert."""
        from midscene.core.agent.run_gherkin_scenario import run_gherkin_scenario as run_scenario

        await run_scenario(self, scenario_text, opt)

    async def run_yaml(
        self, yaml_script_content: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run a YAML automation script (upstream agent.runYaml)."""
        from midscene.core.yaml import ScriptPlayer, parse_yaml_script

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


    # -- execution report ---------------------------------------------------


    def _write_execution_report(
        self,
        prompt_str: str,
        action_tasks: List[Dict[str, Any]],
        output: Optional[str],
        error: Optional[BaseException] = None,
        cache_yaml: Optional[str] = None,
    ) -> Optional[str]:
        """Persist the upstream-shaped execution dump for one aiAct run."""
        generate_report = bool(getattr(self.options, "generate_report", True))
        persist_json = bool(
            generate_report
            and getattr(self.options, "persist_execution_dump", False)
        )
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
            execution = self._get_report_builder().add_execution(
                prompt_str, [planning_task, *action_tasks]
            )
            self._last_execution = execution
        except Exception as e:
            logger.warning(f"Failed to build execution dump: {e}")
            return None
        if not generate_report:
            self._notify_dump_update_listeners(execution)
            return None
        try:
            tag = getattr(self.interface_type, "value", self.interface_type)
            name = getattr(self.options, "report_file_name", None)
            if name:
                name = os.path.basename(name)
                if name.lower().endswith((".json", ".html")):
                    name = name.rsplit(".", 1)[0]
            else:
                name = get_report_file_name(tag)
            if persist_json:
                builder = ExecutionDumpBuilder(
                    group_name=getattr(self.options, "group_name", "Midscene Report"),
                    group_description=getattr(
                        self.options, "group_description", ""
                    ),
                    device_type=tag,
                )
                attributes = getattr(self.options, "report_attributes", None)
                if attributes:
                    builder.dump.update(attributes)
                builder.add_execution(prompt_str, [planning_task, *action_tasks])
                json_path = builder.write_to_disk(name)
            else:
                json_path = None
            from midscene.core.report import write_report_html

            # The HTML report is the combined report stream: upstream writes it
            # whenever generateReport is enabled, independent of the per-execution
            # JSON dump (persistExecutionDump).
            write_report_html(self._get_report_builder().to_dict(), name)
            self._notify_dump_update_listeners(execution)
            return json_path
        except Exception as e:
            logger.warning(f"Failed to write execution report: {e}")
            self._notify_dump_update_listeners(execution)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------


    def _check_not_destroyed(self) -> None:
        if self.destroyed:
            raise RuntimeError("Agent has been destroyed")

    async def _time_string(self) -> str:
        if getattr(self.options, "use_device_time", False):
            device_time = getattr(self.interface, "get_device_time", None)
            if device_time is not None:
                try:
                    result = device_time()
                    if asyncio.iscoroutine(result):
                        result = await result
                    return str(result)
                except NotImplementedError:
                    pass
        return time.strftime("%H:%M:%S")

    @property
    def interface_type(self) -> InterfaceType:
        return self.interface.interface_type

    def _get_report_builder(self):
        return report_manager.get_report_builder(self)

    def record_to_report(self, title, opt=None):
        return record_to_report_module.record_to_report(self, title, opt)

    async def record_error_to_report(self, title, opt=None):
        return await record_to_report_module.record_error_to_report(self, title, opt)

    def _report_name(self):
        return report_file_name.report_name(self)

    async def flush_report(self):
        return await report_manager.flush_report(self)

    def _write_report_artifact(self, name, dump):
        return report_manager.write_report_artifact(self, name, dump)

    async def reset_dump(self):
        return await report_manager.reset_dump(self)

    async def finalize_report(self):
        return await report_manager.finalize_report(self)

    def append_execution_dump(self, execution, runner=None):
        return report_manager.append_execution_dump(self, execution, runner)

    def dump_data_string(self, opt=None):
        return report_manager.dump_data_string(self, opt)

    def report_html_string(self, opt=None):
        return report_manager.report_html_string(self, opt)

    def write_out_action_dumps(self, execution_dump=None):
        return report_manager.write_out_action_dumps(self, execution_dump)

    def add_dump_update_listener(self, listener):
        return report_manager.add_dump_update_listener(self, listener)

    def remove_dump_update_listener(self, listener):
        return report_manager.remove_dump_update_listener(self, listener)

    def clear_dump_update_listeners(self):
        return report_manager.clear_dump_update_listeners(self)

    def _notify_dump_update_listeners(self, execution):
        return report_manager.notify_dump_update_listeners(self, execution)


    def log_screenshot(self, title, opt=None):
        # deprecated upstream alias for recordToReport
        return record_to_report_module.record_to_report(self, title, opt)

    async def _execute_planning_action(self, action, distance_ratio=None, cacheable=None):
        return await task_builder.execute_planning_action(
            self, action, distance_ratio, cacheable
        )

    async def _locate_for_action(self, locate_param):
        return await task_builder.locate_for_action(self, locate_param)

    async def _run_locate(self, prompt, context, deep_locate=False, plan_located_element=None):
        return await task_builder.run_locate(
            self, prompt, context, deep_locate, plan_located_element
        )

    async def _rect_from_cache_feature(self, feature):
        return await task_builder.rect_from_cache_feature(self, feature)

    async def _write_locate_cache(self, prompt_str, element, cache, cacheable, replace_index=None):
        return await task_builder.write_locate_cache(
            self, prompt_str, element, cache, cacheable, replace_index
        )

    async def _replay_cached_plan(self, cached_entry, reported=None):
        return await task_builder.replay_cached_plan(self, cached_entry, reported)

    async def get_ui_context(self, action: str = "locate") -> UIContext:
        return await screenshot_preparation.get_ui_context(self, action)

    def _apply_screenshot_shrink(self, context):
        return screenshot_preparation.apply_screenshot_shrink(self, context)

    async def _emit_progress(self, scope, phase, data):
        return await progress.emit_progress(self, scope, phase, data)

    def add_progress_listener(self, listener):
        return progress.add_progress_listener(self, listener)

    def remove_progress_listener(self, listener):
        return progress.remove_progress_listener(self, listener)

    def clear_progress_listeners(self):
        return progress.clear_progress_listeners(self)

    async def run_markdown(self, markdown_path, opt=None):
        return await run_markdown_module.run_markdown(self, markdown_path, opt)


    def _get_task_cache(self):
        return cache_config.get_task_cache(self)

    def start_observing(self, opt=None):
        return observe_node.start_observing(self, opt)


    @staticmethod
    def _to_logical_coords(element: Dict[str, Any], context: UIContext) -> Dict[str, Any]:
        return ui_utils.to_logical_coords(element, context)
