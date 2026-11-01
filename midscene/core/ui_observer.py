"""UI observation: record a time window of frames and query/assert over it.

Synced from upstream packages/core/src/agent/ui-observer.ts (v1.17.4):
frames are sampled at intervalMs (default 1000, min 200), capped at maxFrames
(30), with a watchdog that auto-stops after 5 minutes. stop() freezes the
window; the observation's insight calls evaluate the recorded frame sequence
(upstream screenshotSequence multi-frame prompt).
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .types import UIContext

DEFAULT_INTERVAL_MS = 1000
MIN_INTERVAL_MS = 200
DEFAULT_MAX_FRAMES = 30
DEFAULT_WATCHDOG_MS = 5 * 60 * 1000
MAX_FRAMES_PER_RECORD = 50


class UIObservation:
    """Fixed observation window; insight calls evaluate the recorded frames."""

    def __init__(self, agent, frames: List[str], started_at: int):
        self._agent = agent
        # own the window: the observer keeps sampling into its own buffer.
        # Upstream dedupeRefs drops repeated *frame refs* (one persisted file
        # reused across ticks); here every entry is its own capture, so a
        # repeated screenshot is a real "nothing changed" data point.
        self._frames = list(frames)
        self._representative = frames[-1] if frames else None
        self.started_at = started_at
        self.ended_at = int(time.time() * 1000)
        self._disposed = False

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def _frozen_context(self, base: UIContext) -> UIContext:
        return base.model_copy(
            update={
                "screenshot_base64": self._representative,
                "screenshot_sequence": list(self._frames),
            }
        )

    def _ensure_usable(self) -> None:
        if self._disposed:
            raise RuntimeError("observation has been disposed")
        if not self._frames:
            raise RuntimeError("observation has no recorded frames")

    def _reject_dom_included(self, options: Optional[Dict[str, Any]]) -> None:
        if options and options.get("domIncluded"):
            raise ValueError(
                "UIObservation does not support domIncluded because it only "
                "evaluates recorded screenshots"
            )

    async def ai_query(self, demand: Union[str, Dict[str, str]], opt: Optional[Dict[str, Any]] = None) -> Any:
        self._ensure_usable()
        self._reject_dom_included(opt)
        opt = dict(opt or {})
        opt.pop("domIncluded", None)
        context = self._frozen_context(await self._agent.get_ui_context("aiQuery"))
        runtime = self._agent._resolve_runtime("extract")
        from .ai_model.workflows import ai_extract_element_info

        response = await ai_extract_element_info(
            task_type="extract",
            data_query=demand,
            context=context,
            model_runtime=runtime,
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._agent._resolve_call_context("aiQuery", opt),
            screenshot_sequence=self._frames,
        )
        self._agent._record_usage_metrics("insight", response.get("usage"))
        return response.get("parse_result", {}).get("data")

    async def ai_boolean(self, prompt: str, opt: Optional[Dict[str, Any]] = None) -> bool:
        result = await self._typed_query("Boolean", "aiBoolean", prompt, opt)
        return bool(result)

    async def ai_number(self, prompt: str, opt: Optional[Dict[str, Any]] = None):
        return await self._typed_query("Number", "aiNumber", prompt, opt)

    async def ai_string(self, prompt: str, opt: Optional[Dict[str, Any]] = None) -> str:
        return await self._typed_query("String", "aiString", prompt, opt)

    async def ai_ask(self, prompt: str, opt: Optional[Dict[str, Any]] = None) -> str:
        return await self._typed_query("String", "aiAsk", prompt, opt)

    async def _typed_query(
        self, demand_type: str, api_name: str, prompt: str, opt: Optional[Dict[str, Any]]
    ) -> Any:
        self._ensure_usable()
        self._reject_dom_included(opt)
        opt = dict(opt or {})
        opt.pop("domIncluded", None)
        from .ai_model.prompts.insight import build_type_query_demand_value

        demand_value = build_type_query_demand_value(demand_type, prompt)
        context = self._frozen_context(await self._agent.get_ui_context(api_name))
        runtime = self._agent._resolve_runtime(
            "boolean" if demand_type == "Boolean" else "extract"
        )
        from .ai_model.workflows import ai_extract_element_info

        response = await ai_extract_element_info(
            task_type="extract",
            data_query={demand_type: demand_value},
            context=context,
            model_runtime=runtime,
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._agent._resolve_call_context(api_name, opt),
            screenshot_sequence=self._frames,
        )
        self._agent._record_usage_metrics("insight", response.get("usage"))
        from .agent import _extract_typed_query_result

        data = response.get("parse_result", {}).get("data")
        return _extract_typed_query_result(data, demand_type)

    async def ai_assert(
        self,
        assertion: str,
        message: Optional[str] = None,
        opt: Optional[Dict[str, Any]] = None,
    ):
        """aiAssert over the recorded window; keepRawResponse returns dict."""
        self._ensure_usable()
        self._reject_dom_included(opt)
        opt = dict(opt or {})
        opt.pop("domIncluded", None)
        context = self._frozen_context(await self._agent.get_ui_context("aiAssert"))
        runtime = self._agent._resolve_runtime("boolean")
        from .ai_model.workflows import ai_extract_element_info

        response = await ai_extract_element_info(
            task_type="boolean",
            data_query={"assertion": assertion},
            context=context,
            model_runtime=runtime,
            screenshot_included=opt.get("screenshotIncluded", True),
            context_text=self._agent._resolve_call_context("aiAssert", opt),
            screenshot_sequence=self._frames,
        )
        self._agent._record_usage_metrics("insight", response.get("usage"))
        parse_result = response.get("parse_result", {})
        data = parse_result.get("data")
        passed = bool(data.get("assertion")) if isinstance(data, dict) else bool(data)
        thought = parse_result.get("thought") or ""
        if opt.get("keepRawResponse"):
            failure_message = (
                None
                if passed
                else (
                    f"Assertion failed: {message or assertion}\n"
                    f"Reason: {thought or '(no_reason)'}"
                )
            )
            return {"pass": passed, "thought": thought, "message": failure_message}
        if not passed:
            raise AssertionError(
                f"Assertion failed: {message or assertion}\n"
                f"Reason: {thought or '(no_reason)'}"
            )
        return None

    async def dispose(self) -> None:
        self._disposed = True
        self._frames.clear()


class UIObserver:
    """Record frames from the agent's interface until stopped."""

    def __init__(self, agent, opt: Optional[Dict[str, Any]] = None):
        opt = opt or {}
        self.interval_ms = max(MIN_INTERVAL_MS, int(opt.get("intervalMs", DEFAULT_INTERVAL_MS)))
        self.max_frames = max(2, int(opt.get("maxFrames", DEFAULT_MAX_FRAMES)))
        self.watchdog_ms = int(opt.get("watchdogMs", DEFAULT_WATCHDOG_MS))
        self._agent = agent
        self._frames: List[str] = []
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_requested = False
        self._observation: Optional[UIObservation] = None
        self._stop_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self.started_at = 0

    @property
    def buffered_frame_count(self) -> int:
        return len(self._frames)

    async def start(self) -> None:
        if self._loop_task is not None or self._stop_requested:
            raise RuntimeError("observer has already started")
        self.started_at = int(time.time() * 1000)
        await self._capture_once()
        self._loop_task = asyncio.ensure_future(self._run_loop())
        if self.watchdog_ms > 0:
            self._watchdog_task = asyncio.ensure_future(self._watchdog())
        logger.info(
            f"UI observation started (interval={self.interval_ms}ms, "
            f"maxFrames={self.max_frames})"
        )

    async def _capture_once(self) -> None:
        # Upstream captureOnce swallows per-tick failures: one bad screenshot
        # must not abort the recording window.
        try:
            context = await self._agent.get_ui_context("observe")
        except Exception as e:
            logger.warning(f"observation frame capture failed, skipping tick: {e}")
            return
        self._frames.append(context.screenshot_base64)
        if len(self._frames) > self.max_frames:
            self._frames = self._thin_buffer(self._frames)

    def _thin_buffer(self, frames: List[str]) -> List[str]:
        """Drop redundant frames, always keeping the first and the last."""
        if len(frames) <= 1:
            return frames
        is_change_point = [frames[i] != frames[i - 1] for i in range(1, len(frames))]
        is_change_point.insert(0, True)
        is_change_point[-1] = True

        result: List[str] = []
        static_counter = 0
        for index, frame in enumerate(frames):
            if is_change_point[index]:
                result.append(frame)
                static_counter = 0
            elif static_counter % 2 == 0:
                result.append(frame)
                static_counter += 1
            else:
                static_counter += 1

        if len(result) > self.max_frames:
            step = len(result) / self.max_frames
            result = [result[int(index * step)] for index in range(self.max_frames)]
            result[-1] = frames[-1]
        return result

    async def _run_loop(self) -> None:
        while not self._stop_requested:
            tick_start = int(time.time() * 1000)
            await self._capture_once()
            # deadline-based pacing so a slow capture does not drift the window
            while (
                not self._stop_requested
                and int(time.time() * 1000) - tick_start < self.interval_ms
            ):
                await asyncio.sleep(0.05)

    async def _watchdog(self) -> None:
        await asyncio.sleep(self.watchdog_ms / 1000)
        if not self._stop_requested:
            logger.warning(
                f"UIObserver auto-stopped after {self.watchdog_ms}ms. "
                "Call observer.stop() explicitly to avoid this."
            )
            try:
                await self.stop()
            except Exception as e:
                logger.warning(f"UIObserver auto-stop failed: {e}")

    def stop(self):
        """Stop recording and return the fixed observation window.

        Synchronous on purpose: the task is memoized before the first await
        (upstream `stopPromise`), so a watchdog auto-stop and an explicit
        stop() can never finalize two different windows.
        """
        if self._stop_task is None:
            self._stop_task = asyncio.ensure_future(self._finalize_stop())
        # shield so a cancelled awaiter cannot drop the window mid-finalize
        return asyncio.shield(self._stop_task)

    async def _finalize_stop(self) -> UIObservation:
        self._stop_requested = True
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None
        if not self._frames:
            await self._capture_once()
        if len(self._frames) > MAX_FRAMES_PER_RECORD:
            logger.warning(
                f"exporting {len(self._frames)} frames (soft limit "
                f"{MAX_FRAMES_PER_RECORD}): every frame goes to the model, "
                "consider increasing intervalMs or decreasing maxFrames"
            )
        self._observation = UIObservation(
            self._agent, self._frames, self.started_at
        )
        return self._observation

    async def dispose(self) -> None:
        """Stop recording if needed and release the recorded frames."""
        try:
            # stop() is memoized, so awaiting it here also joins a stop() the
            # caller never awaited (upstream dispose does the same)
            await self.stop()
        except Exception as e:
            logger.warning(f"observation stopped with an error on dispose: {e}")
        if self._observation is not None:
            await self._observation.dispose()
        self._frames = []
