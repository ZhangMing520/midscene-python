"""Action readiness callback (upstream agent/action-readiness.ts)."""

import asyncio
import time
from typing import Any

from loguru import logger

from midscene.core.types import AbortError

ACTION_READINESS_ERROR_CODE = "ACTION_READINESS_FAILED"


class ActionReadinessError(RuntimeError):
    """Wrapper marking a waitForActionReady callback failure."""

    code = ACTION_READINESS_ERROR_CODE

    def __init__(self, phase: str, action_name: Any, cause: Any) -> None:
        super().__init__(
            f"waitForActionReady {phase} failed for {action_name}: {cause}"
        )
        self.name = "ActionReadinessError"
        self.cause = cause
        self.action_name = action_name


def is_action_readiness_error(error: Any) -> bool:
    """Recognize an ActionReadinessError, including a bounded cause chain."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, "code", None) == ACTION_READINESS_ERROR_CODE:
            return True
        error = getattr(error, "cause", None)
    return False


def _action_field(action: Any, name: str) -> Any:
    if isinstance(action, dict):
        return action.get(name)
    return getattr(action, name, None)


def _throw_if_aborted(signal: Any) -> None:
    if signal is None:
        return
    thrower = getattr(signal, "throw_if_aborted", None)
    if callable(thrower):
        thrower()
        return
    if getattr(signal, "aborted", False) or getattr(signal, "is_set", lambda: False)():
        raise AbortError("Operation interrupted by an external abort signal.")


class ActionReadiness:
    """Await application readiness after a successful action."""

    def __init__(self, callback: Any) -> None:
        if not callable(callback):
            raise TypeError("waitForActionReady must be a function")
        self._callback = callback

    async def wait(
        self,
        action: Any,
        signal: Any = None,
        resource: Any = None,
    ) -> None:
        """Invoke the readiness callback; slow waits only warn."""
        _throw_if_aborted(signal)
        action_name = _action_field(action, "name")
        started = time.time()
        warned = False

        import inspect

        try:
            callback_result = self._callback({"action": action, "signal": signal})
            if inspect.isawaitable(callback_result):
                completion = asyncio.ensure_future(callback_result)
            else:
                completion = asyncio.get_event_loop().create_future()
                completion.set_result(callback_result)
        except Exception as error:
            _throw_if_aborted(signal)
            raise ActionReadinessError("wait", action_name, error) from error

        if signal is not None and resource is not None:
            try:
                from midscene.core.test_runner.engine.resource_operations import (
                    track_resource_operation,
                )

                completion = track_resource_operation(
                    resource, completion, signal, "readiness"
                )
            except Exception as error:  # noqa: BLE001 - tracking is best effort
                logger.debug(f"readiness resource tracking unavailable: {error}")

        poller = (
            asyncio.ensure_future(completion)
            if not isinstance(completion, asyncio.Future)
            else completion
        )
        while not poller.done():
            await asyncio.sleep(0.05)
            if not warned and time.time() - started > 5:
                logger.warning(
                    f"waitForActionReady for {action_name} "
                    f"({_action_field(action, 'id')}) is still pending after "
                    "5000ms; continuing to wait."
                )
                warned = True

        try:
            if signal is not None:
                _throw_if_aborted(signal)
            await poller
            if signal is not None:
                _throw_if_aborted(signal)
        except AbortError:
            raise
        except Exception as error:
            if signal is not None:
                _throw_if_aborted(signal)
            raise ActionReadinessError("wait", action_name, error) from error


async def wait_for_action_ready(options: Any, action: dict[str, Any]) -> None:
    """Await the user's waitForActionReady callback after a successful action.

    Slow waits only warn; callback failures surface as ActionReadinessError.
    """
    callback = getattr(options, "wait_for_action_ready", None)
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
        raise ActionReadinessError("wait", action.get("type"), e) from e


__all__ = [
    "ACTION_READINESS_ERROR_CODE",
    "ActionReadiness",
    "ActionReadinessError",
    "is_action_readiness_error",
    "wait_for_action_ready",
]
