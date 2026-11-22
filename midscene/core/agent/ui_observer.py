"""UI observation: record a time window of frames and query/assert over it.

Synced from upstream packages/core/src/agent/ui-observer.ts (v1.17.4):
frames are sampled at intervalMs (default 1000, min 200), capped at maxFrames
(30), with a watchdog that auto-stops after 5 minutes. stop() freezes the
window; the observation's insight calls evaluate the recorded frame sequence
(upstream screenshotSequence multi-frame prompt).
"""

import asyncio
import base64
import inspect
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from midscene.core.agent.screenshot_preparation import (
    prepare_screenshot_for_persistence,
)
from midscene.core.agent.utils import _empty_tree
from midscene.core.types import Size, UIContext
from midscene.shared.agent_tools.observation_record import (
    UIObservationRecordWriter,
    clone_ui_observation_record,
)
from midscene.shared.img.transform import create_img_base64_by_format

DEFAULT_INTERVAL_MS = 1000
MIN_INTERVAL_MS = 200
DEFAULT_MAX_FRAMES = 30
DEFAULT_WATCHDOG_MS = 5 * 60 * 1000
MAX_FRAMES_PER_RECORD = 50
FIRST_FRAME_TIMEOUT_MS = 3000
DECODE_BATCH_SIZE = 4


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
        from midscene.core.ai_model.workflows import ai_extract_element_info

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
        from midscene.core.ai_model.prompt.insight import build_type_query_demand_value

        demand_value = build_type_query_demand_value(demand_type, prompt)
        context = self._frozen_context(await self._agent.get_ui_context(api_name))
        runtime = self._agent._resolve_runtime(
            "boolean" if demand_type == "Boolean" else "extract"
        )
        from midscene.core.ai_model.workflows import ai_extract_element_info

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
        from midscene.core.agent.utils import _extract_typed_query_result

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
        from midscene.core.ai_model.workflows import ai_extract_element_info

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


def _deps_value(deps: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if isinstance(deps, dict):
            if key in deps:
                return deps[key]
        elif hasattr(deps, key):
            return getattr(deps, key)
    return default


def _frame_path_data_url(path: str, mime_type: str) -> str:
    raw = Path(path).read_bytes()
    image_format = "png" if mime_type == "image/png" else "jpeg"
    return create_img_base64_by_format(
        image_format, base64.b64encode(raw).decode("ascii")
    )


class UIObservationImpl:
    """Fixed observation window implementation (upstream UIObservationImpl)."""

    def __init__(
        self,
        record: Dict[str, Any],
        insight: Any,
        dispose_record: Optional[Any] = None,
        on_disposed: Optional[Any] = None,
    ) -> None:
        self._disposed = False
        self._record = clone_ui_observation_record(record)
        self._insight = insight
        self._dispose_record = dispose_record
        self._on_disposed = on_disposed

    @property
    def frame_count(self) -> int:
        return len(self._record["frames"])

    @property
    def started_at(self) -> int:
        return self._record["startedAt"]

    @property
    def ended_at(self) -> int:
        return self._record["endedAt"]

    def _ensure_usable(self) -> None:
        if self._disposed:
            raise RuntimeError("UI observation has been disposed")

    @staticmethod
    def _ensure_fixed_window_options(options: Optional[Dict[str, Any]]) -> None:
        if options is not None and "domIncluded" in options:
            raise ValueError(
                "UIObservation does not support domIncluded because it only "
                "evaluates recorded screenshots"
            )

    async def ai_query(
        self,
        demand: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_query(demand, options)

    async def ai_boolean(
        self,
        prompt: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_boolean(prompt, options)

    async def ai_number(
        self,
        prompt: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> float:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_number(prompt, options)

    async def ai_string(
        self,
        prompt: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_string(prompt, options)

    async def ai_ask(
        self,
        prompt: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_ask(prompt, options)

    async def ai_assert(
        self,
        assertion: Any,
        message: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        self._ensure_usable()
        self._ensure_fixed_window_options(options)
        return await self._insight.ai_assert(assertion, message, options)

    async def export_record(self) -> Dict[str, Any]:
        self._ensure_usable()
        return clone_ui_observation_record(self._record)

    async def dispose(self) -> None:
        if self._disposed:
            return
        if self._dispose_record is not None:
            result = self._dispose_record()
            if inspect.isawaitable(result):
                await result
        self._disposed = True
        if self._on_disposed is not None:
            result = self._on_disposed()
            if inspect.isawaitable(result):
                await result


class UIObserverImpl:
    """Record an explicit screen window (upstream UIObserverImpl)."""

    def __init__(self, deps: Any, opt: Optional[Dict[str, Any]] = None) -> None:
        opt = opt or {}
        self._deps = deps
        self._frames: List[Dict[str, Any]] = []
        self._source: Any = None
        self._using_fallback = False
        self._stopped = False
        self._disposed = False
        self._loop_task: Optional[asyncio.Future] = None
        self._stop_future: Optional[asyncio.Future] = None
        self._representative: Optional[UIContext] = None
        self._representative_frame: Optional[Dict[str, Any]] = None
        self._watchdog_task: Optional[asyncio.Future] = None
        self._persist_future: Optional[asyncio.Future] = None
        self._persisted_by_ref: Dict[Any, Dict[str, Any]] = {}
        self._observation: Optional[UIObservationImpl] = None
        self._started_at = 0
        self._interval_ms = max(
            MIN_INTERVAL_MS,
            int(opt.get("intervalMs", opt.get("interval_ms", DEFAULT_INTERVAL_MS))),
        )
        self._max_frames = max(
            2, int(opt.get("maxFrames", opt.get("max_frames", DEFAULT_MAX_FRAMES)))
        )
        self._watchdog_ms = int(
            opt.get("watchdogMs", opt.get("watchdog_ms", DEFAULT_WATCHDOG_MS))
        )
        self._screenshot_shrink_factor = _deps_value(
            deps, "screenshotShrinkFactor", "screenshot_shrink_factor", default=1
        )
        writer = _deps_value(
            deps, "observationRecordWriter", "observation_record_writer"
        )
        self._writer = writer or UIObservationRecordWriter()

    @property
    def buffered_frame_count(self) -> int:
        return len(self._frames)

    async def start(self) -> None:
        if self._loop_task is not None or self._stopped:
            raise RuntimeError("observer has already started")
        self._started_at = int(time.time() * 1000)
        open_source = _deps_value(
            self._deps, "openFrameSource", "open_frame_source"
        )
        try:
            self._source = await open_source() if callable(open_source) else None
        except Exception as error:  # noqa: BLE001 - fallback is expected
            logger.debug(
                f"frame source unavailable, using screenshot fallback: {error}"
            )
            self._source = None
        self._using_fallback = self._source is None
        if not self._using_fallback:
            latest = getattr(self._source, "latest", None)
            wait_start = time.time() * 1000
            first_frame = latest() if callable(latest) else None
            while (
                first_frame is None
                and time.time() * 1000 - wait_start < FIRST_FRAME_TIMEOUT_MS
            ):
                await asyncio.sleep(0.05)
                first_frame = latest() if callable(latest) else None
            if first_frame is None:
                logger.debug(
                    f"no first frame within {FIRST_FRAME_TIMEOUT_MS}ms; "
                    "starting anyway"
                )

        await self._capture_once()
        self._loop_task = asyncio.ensure_future(self._run_loop())

        if self._watchdog_ms > 0:
            self._watchdog_task = asyncio.ensure_future(self._watchdog())

    def stop(self) -> Any:
        if self._stop_future is None:
            self._stop_future = asyncio.ensure_future(self._finalize_stop())
        return asyncio.shield(self._stop_future)

    async def _finalize_stop(self) -> UIObservationImpl:
        self._stopped = True
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None

        try:
            if self._frames:
                self._persist_future = asyncio.ensure_future(
                    self._persist_unstored_frames()
                )
            representative_future = self._call_capture_representative()
            if self._persist_future is not None:
                _, representative = await asyncio.gather(
                    self._persist_future, representative_future
                )
            else:
                representative = await representative_future

            last_frame = self._frames[-1] if self._frames else None
            if (
                self._source is not None
                and last_frame is not None
                and last_frame.get("persisted")
            ):
                self._representative_frame = {
                    **last_frame["persisted"],
                    "capturedAt": last_frame["capturedAt"],
                }
                representative = representative.model_copy(
                    update={
                        "screenshot_base64": _frame_path_data_url(
                            self._writer.resolve_frame_path(
                                last_frame["persisted"]
                            ),
                            last_frame["persisted"]["mimeType"],
                        )
                    }
                )
            self._representative = representative
            ended_at = int(time.time() * 1000)
            record = await self._finalize_record(ended_at)
            create_insight = _deps_value(
                self._deps, "createInsight", "create_insight"
            )
            insight = create_insight(record) if callable(create_insight) else None
            self._observation = UIObservationImpl(
                record,
                insight,
                self._writer.dispose,
                _deps_value(self._deps, "onDisposed", "on_disposed"),
            )
            return self._observation
        finally:
            if self._source is not None:
                stop_source = getattr(self._source, "stop", None)
                if callable(stop_source):
                    try:
                        result = stop_source()
                        if inspect.isawaitable(result):
                            await result
                    except Exception as error:  # noqa: BLE001
                        logger.debug(f"error stopping frame source: {error}")
            on_stopped = _deps_value(self._deps, "onStopped", "on_stopped")
            if callable(on_stopped):
                result = on_stopped()
                if inspect.isawaitable(result):
                    await result

    async def _call_capture_representative(self) -> UIContext:
        capture = _deps_value(
            self._deps,
            "capturePreparedRepresentative",
            "capture_prepared_representative",
        )
        if not callable(capture):
            raise RuntimeError("capturePreparedRepresentative is required")
        result = capture()
        if inspect.isawaitable(result):
            return await result
        return result

    async def _finalize_record(self, ended_at: int) -> Dict[str, Any]:
        if not self._stopped or self._representative is None:
            raise RuntimeError(
                "observation must be stopped before finalizing the observed window"
            )
        if self._persist_future is not None:
            await self._persist_future
            self._persist_future = None
        await self._persist_unstored_frames()

        sampled_frames: List[Dict[str, Any]] = []
        for frame in self._frames:
            if not frame.get("persisted"):
                raise RuntimeError("observation frame was not persisted")
            sampled_frames.append(
                {**frame["persisted"], "capturedAt": frame["capturedAt"]}
            )

        if self._representative_frame is None:
            representative = self._representative
            self._representative_frame = self._writer.persist_frame(
                representative.screenshot_base64,
                int(time.time() * 1000),
            )
            representative = representative.model_copy(
                update={
                    "screenshot_base64": _frame_path_data_url(
                        self._writer.resolve_frame_path(
                            self._representative_frame
                        ),
                        self._representative_frame["mimeType"],
                    )
                }
            )
            self._representative = representative

        frames = sampled_frames + [self._representative_frame]
        if len(frames) > MAX_FRAMES_PER_RECORD:
            logger.warning(
                f"WARNING: exporting {len(frames)} frames (soft limit "
                f"{MAX_FRAMES_PER_RECORD}). Running insight against this "
                "observation sends every frame to the model; consider "
                "increasing intervalMs or decreasing maxFrames to reduce "
                "token cost."
            )
        representative = self._representative
        metadata = {
            "startedAt": self._started_at,
            "endedAt": ended_at,
            "shotSize": {
                "width": representative.size.width,
                "height": representative.size.height,
            },
            "shrunkShotToLogicalRatio": (
                representative.shrunk_shot_to_logical_ratio
            ),
        }
        return self._writer.finalize(frames, metadata)

    async def dispose(self) -> None:
        if self._disposed:
            return
        try:
            if self._stop_future is not None:
                await self._stop_future
            elif not self._stopped:
                await self.stop()
        finally:
            if self._observation is not None:
                await self._observation.dispose()
            else:
                self._writer.dispose()
                on_disposed = _deps_value(
                    self._deps, "onDisposed", "on_disposed"
                )
                if callable(on_disposed):
                    result = on_disposed()
                    if inspect.isawaitable(result):
                        await result
            self._frames = []
            self._persisted_by_ref.clear()
            self._observation = None
            self._disposed = True

    async def _persist_unstored_frames(self) -> None:
        unique_frames = self._dedupe_refs(
            [frame for frame in self._frames if not frame.get("persisted")]
        )
        uncached = [
            frame
            for frame in unique_frames
            if frame["ref"] not in self._persisted_by_ref
        ]
        for start in range(0, len(uncached), DECODE_BATCH_SIZE):
            batch = uncached[start : start + DECODE_BATCH_SIZE]
            if self._source is not None:
                decode = getattr(self._source, "decode", None)
                decoded = decode(batch) if callable(decode) else batch
                if inspect.isawaitable(decoded):
                    decoded = await decoded
                decoded = list(decoded)
            else:
                decoded = [frame["ref"] for frame in batch]
            if len(decoded) != len(batch):
                raise RuntimeError(
                    "frame source decode() must return one image per frame handle"
                )
            prepared = [
                await prepare_screenshot_for_persistence(
                    data_url,
                    {"shrinkFactor": self._screenshot_shrink_factor},
                )
                for data_url in decoded
            ]
            for index, frame in enumerate(batch):
                self._persisted_by_ref[frame["ref"]] = (
                    self._writer.persist_frame(
                        prepared[index], frame["capturedAt"]
                    )
                )
        for frame in self._frames:
            if not frame.get("persisted"):
                frame["persisted"] = self._persisted_by_ref.get(frame["ref"])

    async def _capture_once(self) -> None:
        try:
            if self._source is not None:
                latest = getattr(self._source, "latest", None)
                frame = latest() if callable(latest) else None
                if frame is None:
                    return
                ref = frame["ref"] if isinstance(frame, dict) else frame.ref
                captured_at = (
                    frame.get("capturedAt")
                    if isinstance(frame, dict)
                    else getattr(frame, "captured_at", None)
                ) or int(time.time() * 1000)
                if isinstance(ref, str) and ref.startswith("data:image/"):
                    prepared = await prepare_screenshot_for_persistence(
                        ref, {"shrinkFactor": self._screenshot_shrink_factor}
                    )
                    persisted = self._writer.persist_frame(
                        prepared, captured_at
                    )
                    self._push_frame(
                        {
                            "ref": persisted["path"],
                            "capturedAt": captured_at,
                            "persisted": persisted,
                        }
                    )
                else:
                    self._push_frame(
                        {"ref": ref, "capturedAt": captured_at}
                    )
                return
            capture = _deps_value(
                self._deps, "captureRawScreenshot", "capture_raw_screenshot"
            )
            raw = capture() if callable(capture) else ""
            if inspect.isawaitable(raw):
                raw = await raw
            prepared = await prepare_screenshot_for_persistence(
                raw, {"shrinkFactor": self._screenshot_shrink_factor}
            )
            persisted = self._writer.persist_frame(
                prepared, int(time.time() * 1000)
            )
            self._push_frame(
                {
                    "ref": persisted["path"],
                    "capturedAt": persisted["capturedAt"],
                    "persisted": persisted,
                }
            )
        except Exception as error:  # noqa: BLE001 - one bad tick is skipped
            logger.debug(f"frame capture failed, skipping tick: {error}")

    async def _run_loop(self) -> None:
        while not self._stopped:
            tick_start = time.time() * 1000
            await self._capture_once()
            while (
                not self._stopped
                and time.time() * 1000 - tick_start < self._interval_ms
            ):
                await asyncio.sleep(0.05)

    async def _watchdog(self) -> None:
        await asyncio.sleep(self._watchdog_ms / 1000)
        if not self._stopped:
            logger.warning(
                f"UIObserver auto-stopped after {self._watchdog_ms}ms. "
                "Call observer.stop() explicitly to avoid this."
            )
            try:
                await self.stop()
            except Exception:  # noqa: BLE001 - watchdog must not crash
                pass

    def _push_frame(self, frame: Dict[str, Any]) -> None:
        self._frames.append(frame)
        if len(self._frames) > self._max_frames:
            self._frames = self._thin_buffer(self._frames)
            self._writer.prune_frames(
                [
                    frame["persisted"]
                    for frame in self._frames
                    if frame.get("persisted")
                ]
            )
            logger.debug(
                f"frame buffer thinned to {len(self._frames)} frames"
            )

    def _thin_buffer(
        self, frames: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if len(frames) <= 1:
            return frames
        is_change_point = [
            frames[index]["ref"] != frames[index - 1]["ref"]
            for index in range(1, len(frames))
        ]
        is_change_point.insert(0, True)
        is_change_point[-1] = True

        result: List[Dict[str, Any]] = []
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
        if len(result) > self._max_frames:
            step = len(result) / self._max_frames
            sampled = [
                result[int(index * step)]
                for index in range(self._max_frames)
            ]
            sampled[-1] = result[-1]
            result = sampled
        return result

    @staticmethod
    def _dedupe_refs(
        frames: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        seen: List[Any] = []
        result: List[Dict[str, Any]] = []
        for frame in frames:
            if frame["ref"] not in seen:
                seen.append(frame["ref"])
                result.append(frame)
        return result


def ui_context_from_observation_record(
    record: Dict[str, Any],
) -> UIContext:
    """Rebuild model-facing temporal context from a resolved record."""
    if record.get("type") != "midscene_ui_observation" or record.get(
        "version"
    ) != 1:
        raise ValueError("invalid UI observation record type or version")
    if not record.get("frames"):
        raise ValueError("UI observation record contains no frames")
    shot_size = record["shotSize"]
    if not (shot_size["width"] > 0 and shot_size["width"] != float("inf")):
        raise ValueError("UI observation record shot width must be positive")
    if not (shot_size["height"] > 0 and shot_size["height"] != float("inf")):
        raise ValueError("UI observation record shot height must be positive")
    ratio = record["shrunkShotToLogicalRatio"]
    if not (ratio > 0 and ratio != float("inf")):
        raise ValueError(
            "UI observation record screenshot ratio must be positive"
        )

    screenshot_sequence = [
        _frame_path_data_url(frame["path"], frame["mimeType"])
        for frame in record["frames"]
    ]
    return UIContext(
        screenshot_base64=screenshot_sequence[-1],
        screenshot_sequence=screenshot_sequence,
        size=Size(width=shot_size["width"], height=shot_size["height"]),
        content=[],
        tree=_empty_tree(shot_size["width"], shot_size["height"]),
        shrunk_shot_to_logical_ratio=ratio,
    )


__all__ = [
    "DEFAULT_INTERVAL_MS",
    "DEFAULT_MAX_FRAMES",
    "DEFAULT_WATCHDOG_MS",
    "MAX_FRAMES_PER_RECORD",
    "MIN_INTERVAL_MS",
    "UIObservation",
    "UIObservationImpl",
    "UIObserver",
    "UIObserverImpl",
    "ui_context_from_observation_record",
]
