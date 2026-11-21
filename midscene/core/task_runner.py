"""Sequential execution task runner (upstream core/src/task-runner.ts)."""

import inspect
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from midscene.core.task_timing import set_timing_field_once

TASK_RUNNER_UI_CONTEXT_CACHE_TTL_MS = 300
MAX_SERIALIZED_STRING_LENGTH = 4096
TRUNCATED_STRING_SUFFIX = "… [truncated]"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def truncate_serialized_error_string(value: str) -> str:
    if len(value) <= MAX_SERIALIZED_STRING_LENGTH:
        return value
    keep = MAX_SERIALIZED_STRING_LENGTH - len(TRUNCATED_STRING_SUFFIX)
    return f"{value[:keep]}{TRUNCATED_STRING_SUFFIX}"


def _read_diagnostic(error: Any, keys: List[str]) -> Optional[Any]:
    for key in keys:
        value = getattr(error, key, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            return truncate_serialized_error_string(value)
    return None


def _error_stack(error: Any) -> Optional[str]:
    if isinstance(error, BaseException) and error.__traceback__ is not None:
        return "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
    stack = getattr(error, "stack", None)
    return stack if isinstance(stack, str) else None


def serialize_error(error: Any) -> Dict[str, Any]:
    """Bounded diagnostic object for reports and transports."""
    if not isinstance(error, BaseException) and not hasattr(error, "message"):
        message = truncate_serialized_error_string(str(error))
        return {
            "name": "NonError",
            "message": message if message.strip() else "Empty string thrown",
        }

    name = getattr(error, "name", None) or type(error).__name__ or "Error"
    serialized_name = truncate_serialized_error_string(name)
    message = getattr(error, "message", None)
    if not isinstance(message, str) or not message:
        message = str(error) or None
    serialized: Dict[str, Any] = {
        "name": serialized_name,
        "message": truncate_serialized_error_string(
            message or f"{serialized_name} without a message"
        ),
    }
    stack = _error_stack(error)
    if stack:
        serialized["stack"] = truncate_serialized_error_string(stack)

    code = _read_diagnostic(error, ["code"])
    status = _read_diagnostic(error, ["status", "statusCode"])
    request_id = _read_diagnostic(error, ["requestId", "requestID"])
    if code is not None:
        serialized["code"] = code
    if status is not None:
        serialized["status"] = status
    if request_id is not None:
        serialized["requestId"] = request_id
    return serialized


def serialize_task_error(error: Any, signal: Any = None) -> Dict[str, Any]:
    serialized = serialize_error(error)
    # Do not relabel an unrelated error that races with cancellation.
    if signal is not None and getattr(signal, "aborted", False):
        if error is getattr(signal, "reason", None):
            serialized["message"] = truncate_serialized_error_string(
                "Operation interrupted by an external abort signal.\n"
                f"Reason: {serialized['message']}"
            )
    return serialized


def serialize_error_task(task: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not task:
        return None
    result: Dict[str, Any] = {
        "taskId": truncate_serialized_error_string(str(task.get("taskId", ""))),
        "type": task.get("type"),
        "status": task.get("status"),
    }
    if task.get("subType") is not None:
        result["subType"] = truncate_serialized_error_string(str(task["subType"]))
    if task.get("thought") is not None:
        result["thought"] = truncate_serialized_error_string(str(task["thought"]))
    if task.get("errorMessage") is not None:
        result["errorMessage"] = truncate_serialized_error_string(
            str(task["errorMessage"])
        )
    return result


class TaskExecutionError(Exception):
    """Failure raised after the runner records the failing task."""

    code = "TASK_EXECUTION_FAILED"

    def __init__(
        self, error: Dict[str, Any], task: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(error.get("message"))
        self.name = "TaskExecutionError"
        self.cause = error
        self.task = task
        self.stack = truncate_serialized_error_string(
            "".join(traceback.format_exception(type(self), self, None))
        )

    def to_json(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "code": self.code,
            "message": self.message,
            "cause": self.cause,
        }
        if self.task is not None:
            result["task"] = self.task
        return result

    @property
    def message(self) -> str:
        return str(self)


class TaskRunner:
    """Run pending execution tasks sequentially and record their lifecycle."""

    def __init__(
        self,
        name: str,
        ui_context_builder: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        options = options or {}
        self.id = uuid.uuid4().hex
        initial_tasks = options.get("tasks") or []
        self.name = name
        self.tasks: List[Dict[str, Any]] = [
            self._mark_task_as_pending(task) for task in initial_tasks
        ]
        self.status = "pending" if initial_tasks else "init"
        self.on_task_start = options.get("onTaskStart")
        self._ui_context_builder = ui_context_builder
        self._abort_signal = options.get("abortSignal")
        self._on_snapshot_change = options.get("onSnapshotChange")
        self._on_task_event = options.get("onTaskEvent")
        self._execution_log_time = int(time.time() * 1000)
        self._reference_image_urls = {
            image.get("url") if isinstance(image, dict) else getattr(image, "url", None)
            for image in options.get("referenceImages") or []
        }
        self._reference_image_urls.discard(None)
        self._last_ui_context: Optional[Dict[str, Any]] = None

    # -- lifecycle helpers -------------------------------------------------

    def _throw_if_aborted(self) -> None:
        if self._abort_signal is not None and getattr(
            self._abort_signal, "aborted", False
        ):
            self._abort_signal.throw_if_aborted()

    def _mark_task_as_pending(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"taskId": uuid.uuid4().hex, "status": "pending", **task}

    async def _emit_snapshot_change(self, error: Any = None) -> None:
        if self._on_snapshot_change is None:
            return
        await _maybe_await(self._on_snapshot_change(self, error))

    async def _emit_task_event(self, kind: str, task: Dict[str, Any]) -> None:
        if self._on_task_event is None:
            return
        try:
            await _maybe_await(
                self._on_task_event({"kind": kind, "task": task, "runner": self})
            )
        except Exception as error:  # noqa: BLE001 - listener errors stay isolated
            logger.error(f"Error in onTaskEvent listener: {error}")

    async def _get_ui_context(
        self, force_refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        self._throw_if_aborted()
        now = int(time.time() * 1000)
        if (
            not force_refresh
            and self._last_ui_context is not None
            and now - self._last_ui_context["capturedAt"]
            <= TASK_RUNNER_UI_CONTEXT_CACHE_TTL_MS
        ):
            return self._last_ui_context["uiContext"]
        try:
            ui_context = await _maybe_await(self._ui_context_builder(self._abort_signal))
            self._throw_if_aborted()
            if ui_context is not None:
                self._last_ui_context = {
                    "uiContext": ui_context,
                    "capturedAt": int(time.time() * 1000),
                }
            else:
                self._last_ui_context = None
            return ui_context
        except Exception:
            self._last_ui_context = None
            raise

    async def _capture_screenshot(self) -> Any:
        try:
            ui_context = await self._get_ui_context(force_refresh=True)
            if isinstance(ui_context, dict):
                return ui_context.get("screenshot") or ui_context.get(
                    "screenshot_base64"
                )
            return getattr(ui_context, "screenshot", None) or getattr(
                ui_context, "screenshot_base64", None
            )
        except Exception as error:  # noqa: BLE001 - screenshot is best effort
            logger.error(f"error while capturing screenshot: {error}")
        return None

    def _attach_recorder_item(
        self, task: Dict[str, Any], screenshot: Any, phase: str
    ) -> None:
        if not phase or screenshot is None:
            return
        task.setdefault("recorder", []).append(
            {
                "type": "screenshot",
                "ts": int(time.time() * 1000),
                "screenshot": screenshot,
                "timing": phase,
            }
        )

    def _normalize_status_from_error(
        self, options: Optional[Dict[str, Any]] = None, message: Optional[str] = None
    ) -> None:
        if self.status != "error":
            return
        options = options or {}
        if not options.get("allowWhenError"):
            latest = self.latest_error_task()
            raise AssertionError(
                message
                or "task runner is in error state, cannot proceed\n"
                f"error={latest.get('errorMessage') if latest else None}"
            )
        self.status = "pending" if self.tasks else "init"

    # -- public API --------------------------------------------------------

    async def append(
        self,
        task: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._throw_if_aborted()
        self._normalize_status_from_error(
            options, "task runner is in error state, cannot append task"
        )
        incoming = task if isinstance(task, list) else [task]
        appended = [self._mark_task_as_pending(item) for item in incoming]
        self.tasks.extend(appended)
        if self.status != "running":
            self.status = "pending"
        await self._emit_snapshot_change()
        for appended_task in appended:
            await self._emit_task_event("append", appended_task)

    async def append_and_flush(
        self, task: Any, options: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        await self.append(task, options)
        return await self.flush(options)

    async def flush(
        self, options: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        if self.status == "init" and self.tasks:
            logger.warning(
                "illegal state for task runner, status is init but tasks are not empty"
            )
        self._normalize_status_from_error(
            options, "task runner is in error state"
        )
        if self.status == "running":
            raise AssertionError("task runner is already running")
        if self.status == "completed":
            raise AssertionError("task runner is already completed")

        next_pending_index = next(
            (
                index
                for index, task in enumerate(self.tasks)
                if task.get("status") == "pending"
            ),
            -1,
        )
        if next_pending_index < 0:
            return None

        self.status = "running"
        await self._emit_snapshot_change()
        task_index = next_pending_index
        successfully_completed = True
        previous_find_output: Optional[Dict[str, Any]] = None
        finalize_error: Optional[TaskExecutionError] = None

        while task_index < len(self.tasks):
            task = self.tasks[task_index]
            if task.get("status") != "pending":
                raise AssertionError(
                    f"task status should be pending, but got: {task.get('status')}"
                )
            task_started = False
            try:
                self._throw_if_aborted()
                task_started = True
                task["timing"] = {"start": int(time.time() * 1000)}
                task["status"] = "running"
                await self._emit_snapshot_change()
                await self._emit_task_event("start", task)
                self._throw_if_aborted()
                try:
                    if self.on_task_start is not None:
                        await _maybe_await(
                            self.on_task_start(task, self._abort_signal)
                        )
                except Exception as error:  # noqa: BLE001
                    logger.error(f"error in onTaskStart: {error}")
                self._throw_if_aborted()

                task_type = task.get("type")
                if task_type not in ("Insight", "Action Space", "Planning"):
                    raise AssertionError(f"unsupported task type: {task_type}")
                executor = task.get("executor")
                if executor is None:
                    raise AssertionError(
                        f"executor is required for task type: {task_type}"
                    )

                force_refresh = task_type == "Insight"
                set_timing_field_once(task.get("timing"), "getUiContextStart")
                ui_context = await self._get_ui_context(force_refresh=force_refresh)
                set_timing_field_once(task.get("timing"), "getUiContextEnd")
                self._throw_if_aborted()

                task["uiContext"] = ui_context
                executor_context = {
                    "task": task,
                    "element": (previous_find_output or {}).get("element")
                    if previous_find_output
                    else None,
                    "uiContext": ui_context,
                    "signal": self._abort_signal,
                }

                if task_type == "Insight":
                    if task.get("subType") not in (
                        "Query",
                        "Assert",
                        "WaitFor",
                        "Boolean",
                        "Number",
                        "String",
                    ):
                        raise AssertionError(
                            f"unsupported service subType: {task.get('subType')}"
                        )
                    return_value = await _maybe_await(executor(executor_context))
                elif task_type == "Planning":
                    return_value = await _maybe_await(executor(executor_context))
                    if task.get("subType") == "Locate" and isinstance(
                        return_value, dict
                    ):
                        previous_find_output = return_value.get("output")
                elif task_type == "Action Space":
                    try:
                        return_value = await _maybe_await(executor(executor_context))
                    finally:
                        # Actions invalidate cached UI state regardless of TTL.
                        self._last_ui_context = None
                else:  # pragma: no cover - guarded above
                    return_value = await _maybe_await(executor(executor_context))

                self._throw_if_aborted()
                is_last_task = task_index == len(self.tasks) - 1
                if is_last_task:
                    set_timing_field_once(
                        task.get("timing"), "captureAfterCallingSnapshotStart"
                    )
                    screenshot = await self._capture_screenshot()
                    self._throw_if_aborted()
                    self._attach_recorder_item(task, screenshot, "after-calling")
                    set_timing_field_once(
                        task.get("timing"), "captureAfterCallingSnapshotEnd"
                    )
                self._throw_if_aborted()

                if isinstance(return_value, dict):
                    task.update(return_value)
                task["status"] = "finished"
                timing = task.setdefault("timing", {})
                timing["end"] = int(time.time() * 1000)
                timing["cost"] = timing["end"] - timing.get("start", timing["end"])
                await self._emit_snapshot_change()
                await self._emit_task_event("finish", task)
                task_index += 1
            except BaseException as error:
                if isinstance(error, Exception):
                    successfully_completed = False
                    serialized_error = serialize_task_error(
                        error, self._abort_signal
                    )
                    task["error"] = serialized_error
                    task["errorMessage"] = serialized_error["message"]
                    task["errorStack"] = serialized_error.get("stack")
                    task["status"] = "failed" if task_started else "cancelled"
                    timing = task.get("timing")
                    if task_started and timing:
                        timing["end"] = int(time.time() * 1000)
                        timing["cost"] = timing["end"] - timing.get(
                            "start", timing["end"]
                        )
                    await self._emit_snapshot_change()
                    await self._emit_task_event(
                        "error" if task_started else "cancel", task
                    )
                    break
                raise

        cancelled_tasks: List[Dict[str, Any]] = []
        for index in range(task_index + 1, len(self.tasks)):
            self.tasks[index]["status"] = "cancelled"
            cancelled_tasks.append(self.tasks[index])
        if cancelled_tasks:
            await self._emit_snapshot_change()
            for cancelled_task in cancelled_tasks:
                await self._emit_task_event("cancel", cancelled_task)

        if not successfully_completed:
            self.status = "error"
            error_task = self.latest_error_task()
            if error_task is not None and error_task.get("error") is not None:
                error = error_task["error"]
            elif self._abort_signal is not None and getattr(
                self._abort_signal, "aborted", False
            ):
                error = serialize_task_error(
                    getattr(self._abort_signal, "reason", None), self._abort_signal
                )
            else:
                error = {"name": "Error", "message": "Task execution failed"}
            finalize_error = TaskExecutionError(
                error, serialize_error_task(error_task)
            )
            await self._emit_snapshot_change(finalize_error)
        else:
            self.status = "completed"
            await self._emit_snapshot_change()

        if finalize_error is not None:
            raise finalize_error

        if self.tasks:
            output_index = min(task_index, len(self.tasks) - 1)
            last_task = self.tasks[output_index]
            return {
                "thought": last_task.get("thought"),
                "output": last_task.get("output"),
            }
        return None

    def is_in_error_state(self) -> bool:
        return self.status == "error"

    def latest_error_task(self) -> Optional[Dict[str, Any]]:
        if self.status != "error":
            return None
        for task in reversed(self.tasks):
            if task.get("status") == "failed":
                return task
        return None

    def dump(self) -> Dict[str, Any]:
        """Serialize tasks in the upstream ExecutionDump shape."""
        return {
            "id": self.id,
            "logTime": self._execution_log_time,
            "name": self.name,
            "tasks": [
                {**task, "recorder": task.get("recorder") or []}
                for task in self.tasks
            ],
            "referenceImageUrls": [
                url
                for url in self._reference_image_urls
                if isinstance(url, str) and url.startswith("data:image/")
            ],
        }

    async def append_error_plan(
        self, error_msg: str
    ) -> Dict[str, Any]:
        async def _raise(_context: Any) -> None:
            raise RuntimeError(error_msg or "error without thought")

        await self.append_and_flush(
            {
                "type": "Action Space",
                "subType": "Error",
                "param": {"thought": error_msg},
                "thought": error_msg,
                "executor": _raise,
            }
        )
        return {"output": None, "runner": self}


__all__ = [
    "MAX_SERIALIZED_STRING_LENGTH",
    "TASK_RUNNER_UI_CONTEXT_CACHE_TTL_MS",
    "TRUNCATED_STRING_SUFFIX",
    "TaskExecutionError",
    "TaskRunner",
    "serialize_error",
    "serialize_error_task",
    "serialize_task_error",
    "truncate_serialized_error_string",
]
