"""Observation window helper (upstream agent/observe-node.ts)."""

import asyncio
import time
from typing import Any, Dict, Optional

from midscene.core.test_runner.errors import NodeExecutionError


def start_observing(agent, opt: Optional[Dict[str, Any]] = None):
    """Record a time window of UI frames (upstream startObserving).

    Options: `intervalMs` (default 1000, min 200), `maxFrames` (default 30,
    buffer is thinned past the cap while recording continues) and
    `watchdogMs` (default 5 minutes, 0 disables). `stop()` freezes the
    window into a UIObservation whose insight calls read the frames.

    TODO: docs/quickstart.md covers the YAML flow items but not this Python
    API yet.
    """
    from midscene.core.agent.ui_observer import UIObserver

    if agent._frozen:
        raise RuntimeError(
            "startObserving() cannot be used while the UI context is "
            "frozen (call unfreeze_page_context() first)"
        )
    return UIObserver(agent, opt)


async def _settle(ms: float, signal: Any) -> None:
    """Wait `ms` milliseconds, aborting as soon as the signal fires."""
    if not ms:
        return
    deadline = time.monotonic() + ms / 1000.0
    while True:
        signal.throw_if_aborted()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.05, remaining))


def _prompt_text(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        value = prompt.get("prompt")
        return value if isinstance(value, str) else ""
    return ""


async def execute_observe(agent: Any, value: Dict[str, Any], signal: Any) -> Any:
    """Run one action and assert over its recorded screenshot sequence.

    Shared Agent Node lifecycle; recording and insight remain SDK-owned.
    """
    signal.throw_if_aborted()
    if agent is None or not all(
        callable(getattr(agent, name, None))
        for name in ("start_observing", "ai_act", "flush_report")
    ):
        raise TypeError(
            "observe requires an Agent with start_observing(), ai_act(), and "
            "flush_report()."
        )

    act = value.get("act")
    assertion = value.get("assert")
    settle_ms = value.get("settleMs") or 0
    observer = None
    stop_task: Optional[asyncio.Task] = None
    has_initial_frame = False
    data: Optional[Dict[str, Any]] = None
    errors = []

    def collect(error: BaseException) -> None:
        if not any(error is item for item in errors):
            errors.append(error)

    async def _finalize() -> Any:
        nonlocal data
        observation = await observer.stop()
        # Also retain facts when the action fails or cancellation interrupts
        # settling. A representative frame captured by stop cannot replace a
        # missing baseline.
        if has_initial_frame:
            frame_count = observation.frame_count
            duration_ms = observation.ended_at - observation.started_at
            if not isinstance(frame_count, int) or frame_count < 1 or duration_ms < 0:
                raise RuntimeError(
                    "Observation returned an empty or invalid screenshot window."
                )
            data = {"frameCount": frame_count, "durationMs": duration_ms}
        return observation

    async def stop() -> Any:
        nonlocal stop_task
        if observer is None:
            return None
        if stop_task is None:
            stop_task = asyncio.ensure_future(_finalize())
        return await asyncio.shield(stop_task)

    def abort() -> None:
        # Abort listeners cannot await; the main finally owns settlement.
        if observer is not None:
            asyncio.ensure_future(stop())

    signal.add_event_listener("abort", abort, once=True)
    try:
        # The Runner owns the deadline; an SDK watchdog would truncate the window.
        observer = agent.start_observing({"watchdogMs": 0})
        await observer.start()
        has_initial_frame = observer.buffered_frame_count > 0
        signal.throw_if_aborted()
        if not has_initial_frame:
            raise RuntimeError("Observation did not capture an initial frame.")
        await agent.ai_act(act, {"abortSignal": signal})
        signal.throw_if_aborted()
        await _settle(settle_ms, signal)
        observation = await stop()
        signal.throw_if_aborted()
        result = await observation.ai_assert(
            assertion,
            None,
            {"keepRawResponse": True, "abortSignal": signal},
        )
        result = result or {}
        data = {**(data or {}), **result}
        signal.throw_if_aborted()
        if not result.get("pass"):
            raise RuntimeError(
                result.get("message")
                or result.get("thought")
                or "Observed condition did not hold."
            )
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            raise
        collect(error)
    finally:
        signal.remove_event_listener("abort", abort)
        try:
            await stop()
        except BaseException as error:
            collect(error)
        # Flush automatic reports before cleanup. Recorded frames independently
        # own their data even when automatic reporting is disabled.
        try:
            await agent.flush_report()
        except BaseException as error:
            collect(error)
        if observer is not None:
            try:
                await observer.dispose()
            except BaseException as error:
                collect(error)
    if signal.aborted:
        collect(getattr(signal, "reason", None) or RuntimeError("aborted"))
    text = _prompt_text(assertion)
    if errors:
        cause: Any = errors[0] if len(errors) == 1 else Exception("Observation or cleanup failed.")
        if len(errors) > 1:
            cause = Exception(
                "Observation or cleanup failed: "
                + "; ".join(str(item) for item in errors)
            )
        output: Dict[str, Any] = {"summary": f"Observation failed: {text}"}
        if data:
            output["data"] = data
        raise NodeExecutionError("observe", cause, output)
    return {"summary": f"Observation passed: {text}", "data": data}


__all__ = ["execute_observe", "start_observing"]
