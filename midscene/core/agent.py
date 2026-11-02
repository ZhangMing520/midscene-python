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
import base64
import inspect
import json
import os
import re
import time
import traceback
from pathlib import Path
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
    AbortError,
    AbortSignal,
    AbstractInterface,
    AgentOptions,
    FileChooserHandler,
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

# Transient browser errors worth retrying when building the UI context
# (upstream BROWSER_NAVIGATION_ERROR_PATTERN in web-integration).
BROWSER_NAVIGATION_ERROR_PATTERN = re.compile(
    "execution context was destroyed|frame was detached|target closed|"
    "page has been closed|context was destroyed|net::ERR_ABORTED",
    re.IGNORECASE,
)
CONTEXT_RETRY_MAX = 3
CONTEXT_RETRY_DELAY_MS = 1500

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


_FILE_CHOOSER_ACCEPT_KEYS = ("fileChooserAccept", "file_chooser_accept")
_FILE_CHOOSER_ALLOWED_DIR_KEYS = ("fileChooserAllowedDir", "file_chooser_allowed_dir")
_ABORT_SIGNAL_KEYS = ("abortSignal", "abort_signal")


def _get_opt(opt: Dict[str, Any], keys: tuple, default: Any = None) -> Any:
    for key in keys:
        if opt.get(key) is not None:
            return opt[key]
    return default


def _normalize_file_paths(files: Any) -> List[str]:
    """Resolve file chooser paths and fail early when a file is missing
    (upstream normalizeFilePaths)."""
    items = files if isinstance(files, (list, tuple)) else [files]
    normalized: List[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError("File path must be a non-empty string")
        resolved = Path(item).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"File not found: {item}. Resolved to: {resolved}. "
                f"Current working directory: {Path.cwd()}"
            )
        normalized.append(str(resolved))
    return normalized


def _normalize_file_chooser_accept_in_allowed_dir(
    files: Any, allowed_dir: str
) -> List[str]:
    """Resolve files relative to `allowed_dir` and reject paths escaping it
    (upstream normalizeFileChooserAcceptInAllowedDir)."""
    allowed = Path(allowed_dir).expanduser().resolve()
    items = files if isinstance(files, (list, tuple)) else [files]
    resolved_files: List[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise ValueError("File path must be a non-empty string")
        raw = Path(item).expanduser()
        resolved = (raw if raw.is_absolute() else allowed / raw).resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError:
            raise ValueError(
                "File chooser path must be inside the configured "
                f"fileChooserAllowedDir: {item}"
            ) from None
        resolved_files.append(str(resolved))
    return _normalize_file_paths(resolved_files)


def _is_aborted(signal: Any) -> bool:
    if signal is None:
        return False
    if isinstance(signal, AbortSignal):
        return signal.aborted
    aborted = getattr(signal, "aborted", None)
    if aborted is not None:
        return bool(aborted)
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    raise TypeError(
        "abortSignal must be an AbortSignal, asyncio.Event or threading.Event"
    )


def _throw_if_aborted(signal: Any) -> None:
    if not _is_aborted(signal):
        return
    thrower = getattr(signal, "throw_if_aborted", None)
    if callable(thrower):
        thrower()
        return
    reason = getattr(signal, "reason", None) or "signal already aborted"
    raise AbortError(f"aiAct aborted: {reason}")


async def _read_registration_error(registration: Any) -> Optional[BaseException]:
    error = registration.get_error()
    if inspect.isawaitable(error):
        error = await error
    return error


class _FileChooserAccepter:
    """Holds the file chooser configuration for one aiAct execution
    (upstream FileChooserAccepter)."""

    def __init__(self, interface: AbstractInterface):
        self._interface = interface
        self._registration = None

    async def register(self, files: Any) -> None:
        await self._replace(_normalize_file_paths(files))

    async def register_from_allowed_dir(
        self, files: Any, allowed_dir: str
    ) -> None:
        await self._replace(
            _normalize_file_chooser_accept_in_allowed_dir(files, allowed_dir)
        )

    async def _replace(self, accepted_files: List[str]) -> None:
        previous_error = await self.clear()
        if previous_error:
            raise previous_error
        if not accepted_files:
            return
        if not _supports(self._interface, "register_file_chooser_listener"):
            raise RuntimeError(
                f"File upload is not supported on {self._interface.interface_type}"
            )

        async def handler(chooser: FileChooserHandler) -> None:
            await chooser.accept(accepted_files)

        self._registration = await self._interface.register_file_chooser_listener(
            handler
        )

    async def clear(self) -> Optional[BaseException]:
        registration, self._registration = self._registration, None
        if registration is None:
            return None
        try:
            return await _read_registration_error(registration)
        finally:
            registration.dispose()


async def _with_file_chooser(
    interface: AbstractInterface,
    files: Optional[List[str]],
    action: Callable[[], Any],
) -> Any:
    """Run `action` while accepting `files` on any file chooser dialog
    (upstream withFileChooser)."""
    if not files:
        return await action()
    if not _supports(interface, "register_file_chooser_listener"):
        raise RuntimeError(
            f"File upload is not supported on {interface.interface_type}"
        )

    async def handler(chooser: FileChooserHandler) -> None:
        await chooser.accept(files)

    registration = await interface.register_file_chooser_listener(handler)
    try:
        result = await action()
        error = await _read_registration_error(registration)
        if error:
            raise error
        return result
    finally:
        registration.dispose()


def _env_number(key: str) -> Optional[int]:
    raw = os.environ.get(key)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MARKDOWN_IMAGE_REFERENCE_PATTERN = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")
_MAX_MARKDOWN_IMAGES = 20
_REFERENCE_IMAGE_PREFIX = "参考图片"
_URL_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z\d+.-]*:")


def _markdown_to_ai_act_prompt(
    markdown: str, source_path: Optional[str] = None
) -> Union[str, Dict[str, Any]]:
    """Replace Markdown images with reference-image placeholders
    (upstream markdownToAiActPrompt)."""
    reference_match = _MARKDOWN_IMAGE_REFERENCE_PATTERN.search(markdown)
    if reference_match:
        raise ValueError(
            "runMarkdown does not support reference-style images; "
            "use direct image syntax instead."
        )
    images: List[Dict[str, str]] = []

    def replace(match: "re.Match[str]") -> str:
        url = match.group(2)
        if not url:
            raise ValueError(
                f"Markdown image {_REFERENCE_IMAGE_PREFIX}-"
                f"{len(images) + 1:03d} is missing a URL."
            )
        name = f"{_REFERENCE_IMAGE_PREFIX}-{len(images) + 1:03d}"
        resolved = url
        if source_path and not _URL_SCHEME_PATTERN.match(url) and not os.path.isabs(url):
            resolved = str(Path(source_path).resolve().parent / url)
        images.append({"name": name, "url": resolved})
        if len(images) > _MAX_MARKDOWN_IMAGES:
            raise ValueError(
                "runMarkdown supports at most "
                f"{_MAX_MARKDOWN_IMAGES} images, but found more."
            )
        return name

    prompt = _MARKDOWN_IMAGE_PATTERN.sub(replace, markdown)
    if not images:
        return markdown
    return {
        "prompt": prompt,
        "images": images,
        "convertHttpImage2Base64": True,
    }


_REFERENCE_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def _resolve_reference_image(image, convert_http):
    """Resolve one markdown reference image to a model-ingestable URL."""
    url = image.get("url") if isinstance(image, dict) else None
    if not url or not isinstance(url, str):
        return None
    if url.startswith("data:"):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        if not convert_http:
            return url
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read()
            mime = getattr(resp.headers, "get_content_type", lambda: "image/png")()
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception as e:
            logger.warning(f"Failed to inline reference image {url}: {e}")
            return url
    path = Path(url)
    if path.exists():
        suffix = path.suffix.lstrip(".").lower() or "png"
        mime = _REFERENCE_IMAGE_MIME.get(suffix, "image/png")
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    return None


def _resolve_reference_images(images, convert_http):
    """Resolve a list of markdown reference images to model-ingestable URLs."""
    resolved = []
    for item in images or []:
        url = _resolve_reference_image(item, convert_http)
        if url:
            resolved.append(url)
    return resolved


def _reference_images_from_prompt(task_prompt):
    """Pull reference images out of a markdown-style prompt dict."""
    if isinstance(task_prompt, dict) and task_prompt.get("images"):
        return _resolve_reference_images(
            task_prompt["images"],
            bool(task_prompt.get("convertHttpImage2Base64", False)),
        )
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
        if not usage:
            return
        bucket = self._usage_by_intent.setdefault(
            intent, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            bucket[key] += int(usage.get(key) or 0)

    def _resolve_runtime(self, task_type: str) -> ModelRuntime:
        """Resolve the runtime for a task type with model fallback
        (upstream resolveModelForTaskType). Task types map to config intents:
        extract/boolean -> insight slot, locate/planning -> their own slots."""
        intent = "insight" if task_type in ("extract", "boolean") else task_type
        return resolve_model_for_task_type(self._model_config, intent, task_type)

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

    async def get_ui_context(self, action: str = "locate") -> UIContext:
        if self._frozen and self.frozen_context is not None:
            return self.frozen_context
        attempt = 0
        while True:
            try:
                context = await self.interface.get_context()
                break
            except Exception as e:
                if (
                    attempt < CONTEXT_RETRY_MAX
                    and self.is_retryable_context_error(e)
                ):
                    logger.debug(
                        "retryable context error "
                        f"(attempt {attempt + 1}/{CONTEXT_RETRY_MAX}), "
                        f"retrying in {CONTEXT_RETRY_DELAY_MS}ms: {e}"
                    )
                    await asyncio.sleep(CONTEXT_RETRY_DELAY_MS / 1000)
                    attempt += 1
                    continue
                raise
        context = self._apply_screenshot_shrink(context)
        if self._frozen:
            self.frozen_context = context
        return context

    def _apply_screenshot_shrink(self, context: UIContext) -> UIContext:
        """Record the screenshot-space -> logical-space ratio and downscale the
        screenshot when asked (upstream commonContextParser:
        shrunkShotToLogicalRatio = dpr / screenshotShrinkFactor,
        dpr = physicalWidth / logicalWidth)."""
        factor = float(getattr(self.options, "screenshot_shrink_factor", 1.0) or 1.0)
        try:
            import base64 as _b64
            import io as _io

            from PIL import Image

            raw = context.screenshot_base64
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            image = Image.open(_io.BytesIO(_b64.b64decode(raw)))
            physical_width, physical_height = image.size
            logical_width = context.size.width or physical_width
            dpr = physical_width / logical_width if logical_width else 1.0
            ratio = dpr / factor
            if factor <= 1:
                if ratio == 1.0:
                    return context
                return context.model_copy(
                    update={"shrunk_shot_to_logical_ratio": ratio}
                )
            target_width = max(1, round(physical_width / factor))
            target_height = max(1, round(physical_height / factor))
            shrunk = image.resize((target_width, target_height))
            buffer = _io.BytesIO()
            shrunk.save(buffer, format="PNG")
            shrunk_base64 = _b64.b64encode(buffer.getvalue()).decode("ascii")
            return context.model_copy(
                update={
                    "screenshot_base64": shrunk_base64,
                    "shrunk_shot_to_logical_ratio": ratio,
                }
            )
        except Exception as e:
            logger.warning(f"screenshot shrink failed, using original: {e}")
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
            from .ai_model.workflows.context_utils import render_ai_context

            rendered = render_ai_context(context)
            if rendered:
                parts.append(rendered)
        return "\n\n".join(parts) if parts else None

    async def _wait_for_action_ready(self, action: Dict[str, Any]) -> None:
        """Await the user's waitForActionReady callback after a successful
        action; slow waits only warn (upstream agent/action-readiness.ts)."""
        callback = getattr(self.options, "wait_for_action_ready", None)
        if not callback:
            return
        started = time.time()
        warned = False
        task = asyncio.ensure_future(
            callback({"action": {"name": action.get("type"), "id": None}})
        )
        while not task.done():
            await asyncio.sleep(0.05)
            if not warned and time.time() - started > 5:
                logger.warning(
                    f"waitForActionReady for {action.get('type')} is still "
                    "pending after 5000ms; continuing to wait."
                )
                warned = True
        try:
            await task
        except Exception as e:
            raise RuntimeError(
                f"waitForActionReady failed for {action.get('type')}: {e}"
            ) from e

    def _notify_task_start(self, tip: str) -> None:
        callback: Optional[Callable] = getattr(self.options, "on_task_start_tip", None)
        if callback:
            result = callback(tip)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    # ------------------------------------------------------------------
    # Progress bus (upstream addProgressListener / AgentProgressEvent)
    # ------------------------------------------------------------------

    @staticmethod
    def _action_progress_summary(action: Dict[str, Any]) -> Dict[str, Any]:
        """Structured, presentation-free action descriptor for progress events
        (upstream ai-act-progress summarizers)."""
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

    async def _emit_progress(
        self, scope: str, phase: str, data: Any
    ) -> None:
        if not self._progress_listeners:
            return
        self._progress_sequence += 1
        event = {
            "scope": scope,
            "phase": phase,
            "sequence": self._progress_sequence,
            "data": data,
        }
        for listener in list(self._progress_listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # listeners must never break execution
                logger.warning(f"progress listener threw, ignoring: {e}")

    def add_progress_listener(self, listener: Callable) -> Callable[[], None]:
        """Subscribe to agent progress; returns a remove function."""
        self._progress_listeners.append(listener)

        def remove() -> None:
            self.remove_progress_listener(listener)

        return remove

    def remove_progress_listener(self, listener: Callable) -> None:
        try:
            self._progress_listeners.remove(listener)
        except ValueError:
            pass

    def clear_progress_listeners(self) -> None:
        self._progress_listeners.clear()

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
        reference_images = _reference_images_from_prompt(task_prompt)
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
                        "action": self._action_progress_summary(action),
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
                        "action": self._action_progress_summary(action),
                    },
                )
                try:
                    _throw_if_aborted(abort_signal)
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
                    await asyncio.sleep(
                        getattr(self.options, "wait_after_action_ms", 300) / 1000
                    )
                    await self._wait_for_action_ready(action)
                    await self._emit_progress(
                        "aiAct",
                        "action_done",
                        {
                            "prompt": prompt_str,
                            "action": self._action_progress_summary(action),
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
                        self._build_action_report_task(
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
                            "action": self._action_progress_summary(action),
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
            await self.flush_report()
            # Not every interface owns a transport; those that do (WDA session,
            # browser context) release it here.
            interface_destroy = getattr(self.interface, "destroy", None)
            if asyncio.iscoroutinefunction(interface_destroy):
                await interface_destroy()

    def _get_report_builder(self):
        if self._report_builder is None:
            from .dump import ExecutionDumpBuilder

            tag = getattr(self.interface_type, "value", self.interface_type)
            self._report_builder = ExecutionDumpBuilder(
                group_name=getattr(self.options, "group_name", "Midscene Report"),
                group_description=getattr(self.options, "group_description", ""),
                device_type=tag,
            )
            attributes = getattr(self.options, "report_attributes", None)
            if attributes:
                self._report_builder.dump.update(attributes)
        return self._report_builder

    def record_to_report(
        self,
        title: str,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a log/screenshot entry to the report (upstream
        recordToReport). opt: {content?, screenshots?: [{base64, description?}]}."""
        from .dump import build_execution_task

        opt = opt or {}
        screenshots = opt.get("screenshots") or []
        if opt.get("screenshot_base64"):
            screenshots = [{"base64": opt["screenshot_base64"]}]
        tasks = [
            build_execution_task(
                "Log",
                "Screenshot" if screenshots else "Log",
                {"title": title, "content": opt.get("content", "")},
                output=screenshots or None,
            )
        ]
        execution = self._get_report_builder().add_execution(
            f"Log - {title}", tasks
        )
        self._last_execution = execution
        self._notify_dump_update_listeners(execution)

    # deprecated alias (upstream logScreenshot)
    log_screenshot = record_to_report

    async def record_error_to_report(
        self,
        title: str,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a failed Log entry to the report (upstream recordErrorToReport).

        opt: {error: BaseException, content?, screenshotBase64?}. When no
        screenshot is supplied the current interface screenshot is captured.
        """
        from .dump import build_execution_task

        opt = opt or {}
        error = opt.get("error")
        message = str(error) if error is not None else ""
        error_info: Dict[str, Any] = {
            "name": type(error).__name__ if error is not None else "",
            "message": message,
            "stack": "",
        }
        if isinstance(error, BaseException):
            error_info["stack"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        content = opt.get("content") or message
        screenshot = (
            opt.get("screenshotBase64")
            or opt.get("screenshot_base64")
            or opt.get("screenshot")
        )
        if not screenshot:
            try:
                screenshot = getattr(
                    await self.get_context(), "screenshot_base64", None
                )
            except Exception as capture_error:  # screenshot is best effort
                logger.debug(f"record_error_to_report screenshot failed: {capture_error}")
        output = [{"base64": screenshot}] if screenshot else None
        tasks = [
            build_execution_task(
                "Log",
                "Error",
                {"content": content},
                status="failed",
                error=error_info,
                errorMessage=message,
                errorStack=error_info["stack"],
                output=output,
            )
        ]
        execution = self._get_report_builder().add_execution(
            title, tasks, description=content
        )
        self._last_execution = execution
        self._notify_dump_update_listeners(execution)

    async def set_ai_action_context(self, prompt: str) -> None:
        """Deprecated upstream alias for setAIContext('aiAct', ...)."""
        self.set_ai_context("aiAct", prompt)

    async def set_ai_act_context(self, prompt: str) -> None:
        """Deprecated upstream alias for setAIContext('aiAct', ...)."""
        self.set_ai_context("aiAct", prompt)

    def _report_name(self) -> str:
        if self._report_file_name:
            return self._report_file_name
        name = getattr(self.options, "report_file_name", None)
        if name:
            name = os.path.basename(name)
            if name.lower().endswith((".json", ".html")):
                name = name.rsplit(".", 1)[0]
        else:
            tag = getattr(self.options, "test_id", None) or getattr(
                self.interface_type, "value", self.interface_type
            )
            name = get_report_file_name(tag)
        self._report_file_name = name
        return name

    async def flush_report(self) -> Optional[str]:
        """Write the in-memory report to disk; returns the report path."""
        if self._report_builder is None:
            return None
        name = self._report_name()
        json_path = self._report_builder.write_to_disk(name)
        from .report_viewer import write_report_html

        html_path = write_report_html(self._report_builder.to_dict(), name)
        return html_path or json_path or None

    # ------------------------------------------------------------------
    # Report APIs (upstream resetDump / finalizeReport / dumpDataString ...)
    # ------------------------------------------------------------------

    async def reset_dump(self) -> Dict[str, Any]:
        """Finalize the preceding report and start a fresh execution dump."""
        self._check_not_destroyed()
        try:
            await self.finalize_report()
        except Exception as e:  # failure belongs to the previous report
            logger.warning(f"Failed to finalize previous report; resetting dump: {e}")
        self._check_not_destroyed()
        self._report_builder = None
        self._report_finalized = None
        self._report_file_name = None
        self._last_execution = None
        self._execution_index_by_runner = {}
        return self._get_report_builder().to_dict()

    async def finalize_report(self) -> Optional[str]:
        """Seal the current report and release its in-memory records."""
        if self._report_finalized is not None:
            return self._report_finalized or None
        if self.destroyed:
            raise RuntimeError("Cannot finalize a report using a destroyed Agent.")
        path = await self.flush_report()
        self._report_finalized = path or ""
        # Mirror upstream clearDumpInMemory: records are released after sealing.
        self._report_builder = None
        self._last_execution = None
        self._execution_index_by_runner = {}
        return path

    def append_execution_dump(
        self, execution: Dict[str, Any], runner: Any = None
    ) -> None:
        """Append one execution dump; a runner replaces its previous entry."""
        if self._report_finalized is not None:
            raise RuntimeError(
                "Cannot append to a finalized report. Await resetDump() first."
            )
        builder = self._get_report_builder()
        executions = builder.dump["executions"]
        if runner is not None:
            key = id(runner)
            index = self._execution_index_by_runner.get(key)
            if index is not None:
                executions[index] = execution
            else:
                executions.append(execution)
                self._execution_index_by_runner[key] = len(executions) - 1
        else:
            executions.append(execution)
        self._last_execution = execution

    def dump_data_string(
        self, opt: Optional[Dict[str, Any]] = None
    ) -> str:
        """Serialize the in-memory dump (upstream dumpDataString)."""
        return json.dumps(
            self._get_report_builder().to_dict(),
            ensure_ascii=False,
        )

    def report_html_string(
        self, opt: Optional[Dict[str, Any]] = None
    ) -> str:
        """Render the in-memory dump as a self-contained HTML string."""
        from .report_viewer import render_report_html

        return render_report_html(self._get_report_builder().to_dict(), self._report_name())

    def write_out_action_dumps(
        self, execution_dump: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Persist the current report (JSON + HTML) without disposing the Agent."""
        if self._report_finalized is not None:
            if execution_dump is not None:
                raise RuntimeError(
                    "Cannot append to a finalized report. Await resetDump() first."
                )
            return self._report_finalized or None
        if execution_dump is not None:
            self._last_execution = execution_dump
        name = self._report_name()
        json_path = self._get_report_builder().write_to_disk(name)
        from .report_viewer import write_report_html

        html_path = write_report_html(self._get_report_builder().to_dict(), name)
        return html_path or json_path or None

    def add_dump_update_listener(self, listener: Callable) -> Callable[[], None]:
        """Subscribe to dump updates; returns a remove function."""
        self._dump_update_listeners.append(listener)

        def remove() -> None:
            self.remove_dump_update_listener(listener)

        return remove

    def remove_dump_update_listener(self, listener: Callable) -> None:
        try:
            self._dump_update_listeners.remove(listener)
        except ValueError:
            pass

    def clear_dump_update_listeners(self) -> None:
        self._dump_update_listeners.clear()

    def _notify_dump_update_listeners(
        self, execution: Optional[Dict[str, Any]] = None
    ) -> None:
        if not self._dump_update_listeners:
            return
        dump_string = self.dump_data_string()
        for listener in list(self._dump_update_listeners):
            try:
                result = listener(dump_string, execution)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception as e:  # listeners must never break execution
                logger.warning(f"dump update listener threw, ignoring: {e}")

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

    async def run_markdown(
        self,
        markdown_path: str,
        opt: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Run a Markdown prompt file; images become reference images."""
        self._check_not_destroyed()
        path = Path(markdown_path)
        markdown = path.read_text(encoding="utf-8")
        prompt = _markdown_to_ai_act_prompt(markdown, str(path))
        opt = dict(opt or {})
        opt.setdefault(
            "_internal_report_display",
            {"type": "Markdown", "prompt": path.name},
        )
        return await self.ai_act(prompt, opt)

    def flush_cache(self, options: Optional[Dict[str, Any]] = None) -> None:
        if self._task_cache is None:
            raise RuntimeError("Cache is not configured")
        self._task_cache.flush()

    def start_observing(self, opt: Optional[Dict[str, Any]] = None):
        """Record a time window of UI frames (upstream startObserving).

        Options: `intervalMs` (default 1000, min 200), `maxFrames` (default 30,
        buffer is thinned past the cap while recording continues) and
        `watchdogMs` (default 5 minutes, 0 disables). `stop()` freezes the
        window into a UIObservation whose insight calls read the frames.

        TODO: docs/quickstart.md covers the YAML flow items but not this Python
        API yet.
        """
        from .ui_observer import UIObserver

        if self._frozen:
            raise RuntimeError(
                "startObserving() cannot be used while the UI context is "
                "frozen (call unfreeze_page_context() first)"
            )
        return UIObserver(self, opt)

    async def run_gherkin_scenario(
        self,
        scenario_text: str,
        opt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run a Gherkin scenario: Given/When -> aiAct, Then -> aiAssert."""
        from .gherkin import run_gherkin_scenario as run_scenario

        await run_scenario(self, scenario_text, opt)

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
        return self._to_logical_coords(element, context)

    @staticmethod
    def _to_logical_coords(element: Dict[str, Any], context: UIContext) -> Dict[str, Any]:
        """Scale screenshot-space coordinates back to logical viewport space
        (upstream task-builder.ts divides the shot coordinates by
        shrunkShotToLogicalRatio)."""
        ratio = float(getattr(context, "shrunk_shot_to_logical_ratio", 1.0) or 1.0)
        if ratio == 1.0:
            return element
        center = element.get("center")
        if center:
            element = {
                **element,
                "center": [center[0] / ratio, center[1] / ratio],
            }
        rect = element.get("rect")
        if rect:
            element = {
                **element,
                "rect": {
                    "left": rect["left"] / ratio,
                    "top": rect["top"] / ratio,
                    "width": rect["width"] / ratio,
                    "height": rect["height"] / ratio,
                },
            }
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
            from .report_viewer import write_report_html

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

    def _get_task_cache(self) -> Optional[TaskCache]:
        if self._task_cache is not None:
            return self._task_cache

        cache_config = getattr(self.options, "cache", None)
        cache_id = getattr(self.options, "cache_id", None)
        enabled = is_cache_enabled()
        read_only = False
        write_only = False
        cache_dir: Optional[str] = None

        if isinstance(cache_config, dict):
            strategy = cache_config.get("strategy") or "read-write"
            if strategy not in ("read-only", "read-write", "write-only"):
                raise ValueError(
                    'cache.strategy must be one of "read-only", "read-write", '
                    f'"write-only", but received "{strategy}"'
                )
            read_only = strategy == "read-only"
            write_only = strategy == "write-only"
            cache_id = cache_config.get("id") or cache_id
            cache_dir = cache_config.get("cacheDir") or cache_config.get("cache_dir")
            enabled = True
        elif isinstance(cache_config, str):
            cache_id = cache_config
            enabled = True
        elif cache_config is False:
            return None

        if not enabled and not cache_id:
            return None
        self._task_cache = TaskCache(
            cache_id=cache_id or "midscene-python",
            enabled=True,
            read_only_mode=read_only,
            write_only_mode=write_only,
            cache_dir=cache_dir,
        )
        return self._task_cache

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
