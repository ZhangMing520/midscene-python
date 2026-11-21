"""Agent helpers (upstream agent/utils.ts)."""

import os
from typing import Any, Dict, Optional

from midscene.core.types import AbortError, AbortSignal

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


def _get_opt(opt: Dict[str, Any], keys: tuple, default: Any = None) -> Any:
    for key in keys:
        if opt.get(key) is not None:
            return opt[key]
    return default


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
    raise AbortError(
        f"Operation interrupted by an external abort signal.\nReason: {reason}"
    )


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
