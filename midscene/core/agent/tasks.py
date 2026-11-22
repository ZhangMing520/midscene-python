"""Action task metadata (upstream agent/tasks.ts)."""

import asyncio
import time
from typing import Any, Dict, List, Optional

from midscene.core.agent.utils import _strip_runtime_locate_result
from midscene.core.task_runner import TaskExecutionError
from midscene.core.dump import build_execution_task
from midscene.core.screenshot_item import ScreenshotItem


def record_and_release_screenshot_sequence(
    task: Dict[str, Any],
    ui_context: Any,
) -> None:
    """Surface an observed screenshot sequence in the report timeline."""
    frames = (
        ui_context.get("screenshot_sequence")
        if isinstance(ui_context, dict)
        else getattr(ui_context, "screenshot_sequence", None)
    )
    for frame in frames or []:
        retain = getattr(frame, "retain_for_recording", None)
        if callable(retain):
            retain()

    if frames and len(frames) > 1:
        recorder_items: List[Dict[str, Any]] = []
        for index, frame in enumerate(frames[:-1]):
            if isinstance(frame, str):
                screenshot = ScreenshotItem.create(frame, int(time.time() * 1000))
                captured_at = screenshot.captured_at
            else:
                screenshot = frame
                captured_at = getattr(frame, "captured_at", None) or int(
                    time.time() * 1000
                )
            recorder_items.append(
                {
                    "type": "screenshot",
                    "ts": captured_at,
                    "screenshot": screenshot,
                    "description": (
                        f"Observed frame {index + 1}/{len(frames)}"
                    ),
                    "timing": "observed-frame",
                }
            )
        task["recorder"] = recorder_items + list(task.get("recorder") or [])

    if isinstance(ui_context, dict):
        if "screenshotSequence" in ui_context:
            ui_context["screenshotSequence"] = None
        if "screenshot_sequence" in ui_context:
            ui_context["screenshot_sequence"] = None
    elif hasattr(ui_context, "screenshot_sequence"):
        ui_context.screenshot_sequence = None


class TaskExecutor:
    """Executable-task orchestrator (upstream agent/tasks.ts TaskExecutor).

    The Python Agent already owns the planning loop; this facade exposes the
    upstream task-level API and delegates to the same execution helpers.
    """

    def __init__(
        self,
        interface_instance: Any,
        service: Any = None,
        opts: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._agent = (
            interface_instance
            if hasattr(interface_instance, "ai_act")
            else None
        )
        self.interface = (
            getattr(self._agent, "interface", None)
            if self._agent is not None
            else interface_instance
        )
        self.service = service
        self._opts = opts or {}
        self.task_cache = self._opts.get(
            "taskCache", self._opts.get("task_cache")
        )
        self.replanning_cycle_limit = self._opts.get(
            "replanningCycleLimit", self._opts.get("replanning_cycle_limit")
        )
        self.wait_after_action = self._opts.get(
            "waitAfterAction", self._opts.get("wait_after_action")
        )
        self.on_task_start_callback = self._opts.get(
            "onTaskStart", self._opts.get("on_task_start")
        )

    async def convert_plan_to_executable(
        self,
        plans: List[Dict[str, Any]],
        planning_model: Any,
        locate_model: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from midscene.core.agent.task_builder import TaskBuilder

        builder = TaskBuilder(
            {
                "interfaceInstance": self.interface,
                "service": self.service,
                "taskCache": self.task_cache,
                "actionSpace": self._opts.get(
                    "actionSpace", self._opts.get("action_space", [])
                ),
                "getDefaultModelRuntime": self._opts.get(
                    "getDefaultModelRuntime",
                    lambda: planning_model,
                ),
                "waitAfterAction": self.wait_after_action,
            }
        )
        return await builder.build(plans, planning_model, locate_model, options)

    async def load_yaml_flow_as_planning(
        self,
        user_instruction: Any,
        yaml_string: str,
        report_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._agent is not None:
            replayed = await self._agent._replay_cached_plan(
                {"yamlWorkflow": yaml_string}
            )
            return {"output": None, "replayed": replayed, "runner": None}
        return {"output": None, "runner": None}

    async def sleep(self, ms: float, abort_signal: Any = None) -> None:
        if abort_signal is not None:
            thrower = getattr(abort_signal, "throw_if_aborted", None)
            if callable(thrower):
                thrower()
        await asyncio.sleep(max(0.0, ms) / 1000)

    async def run_plans(
        self,
        title: str,
        plans: List[Dict[str, Any]],
        planning_model: Any,
        locate_model: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        built = await self.convert_plan_to_executable(
            plans, planning_model, locate_model, options
        )
        output = None
        for task in built["tasks"]:
            result = await task["executor"](
                {"task": task, "uiContext": options.get("uiContext")}
            )
            if isinstance(result, dict):
                output = result.get("output", output)
        return {"output": output, "runner": None}

    async def action(
        self,
        user_prompt: Any,
        planning_model: Any,
        locate_model: Any,
        ai_act_context: Optional[str] = None,
        cacheable: Optional[bool] = None,
        replanning_cycle_limit_override: Optional[int] = None,
        effort: str = "balance",
        file_chooser_accept: Optional[List[str]] = None,
        deep_locate: Optional[bool] = None,
        abort_signal: Any = None,
        report_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._agent is None:
            raise RuntimeError("TaskExecutor.action requires an Agent instance")
        opt: Dict[str, Any] = {
            "context": ai_act_context,
            "cacheable": cacheable,
            "effort": effort,
            "fileChooserAccept": file_chooser_accept,
            "deepLocate": deep_locate,
            "abortSignal": abort_signal,
        }
        if replanning_cycle_limit_override is not None:
            opt["replanningCycleLimit"] = replanning_cycle_limit_override
        output = await self._agent.ai_act(user_prompt, opt)
        return {"output": output, "runner": None}

    async def create_type_query_execution(
        self,
        type: str,
        demand: Any,
        model_runtime: Any,
        opt: Optional[Dict[str, Any]] = None,
        multimodal_prompt: Any = None,
        execution_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._agent is None:
            raise RuntimeError(
                "TaskExecutor.createTypeQueryExecution requires an Agent instance"
            )
        opt = opt or {}
        execution_options = execution_options or {}
        query_opt = {**opt, **execution_options}
        if multimodal_prompt:
            query_opt["multimodalPrompt"] = multimodal_prompt
        if type == "Query":
            output = await self._agent.ai_query(demand, query_opt)
        elif type == "Boolean":
            output = await self._agent.ai_boolean(demand, query_opt)
        elif type == "Number":
            output = await self._agent.ai_number(demand, query_opt)
        elif type == "String":
            output = await self._agent.ai_string(demand, query_opt)
        elif type == "Assert":
            output = await self._agent.ai_assert(
                demand, None, {**query_opt, "keepRawResponse": True}
            )
        else:
            raise ValueError(f"Unsupported type query type: {type}")
        return {"output": output, "thought": None, "runner": None}

    async def wait_for(
        self,
        assertion: Any,
        opt: Dict[str, Any],
        model_runtime: Any,
    ) -> Dict[str, Any]:
        if self._agent is None:
            raise RuntimeError("TaskExecutor.waitFor requires an Agent instance")
        output = await self._agent.ai_wait_for(assertion, opt)
        return {"output": output, "runner": None}


__all__ = [
    "TaskExecutionError",
    "TaskExecutor",
    "action_progress_summary",
    "build_action_report_task",
    "record_and_release_screenshot_sequence",
]


def action_progress_summary(action: Dict[str, Any]) -> Dict[str, Any]:
    """Structured, presentation-free action descriptor for progress events."""
    name = action.get("type")
    param = action.get("param") or {}
    summary: Dict[str, Any] = {"name": name}
    locate = param.get("locate") or param.get("from")
    if isinstance(locate, dict):
        if locate.get("prompt"):
            summary["target"] = locate["prompt"]
        bbox = locate.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            summary["bbox"] = [int(v) for v in bbox[:4]]
    elif isinstance(locate, str):
        summary["target"] = locate
    if "target" not in summary and isinstance(param.get("prompt"), str):
        summary["target"] = param["prompt"]
    if "target" not in summary and "bbox" not in summary:
        compact = {
            key: value
            for key, value in param.items()
            if isinstance(value, (str, int, float, bool))
        }
        if compact:
            summary["param"] = compact
    return summary


def build_action_report_task(
    action: Dict[str, Any],
    started_at: float,
    finished_at: float,
    status: str = "finished",
    error: Optional[BaseException] = None,
) -> Dict[str, Any]:
    """Build one Action Space execution task for the report dump."""
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
