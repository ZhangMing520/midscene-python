"""Report usage/timing summaries (upstream core/src/report-stats.ts)."""

import math
from typing import Any, Dict, List, Optional

_USAGE_KEYS = (
    "intent",
    "slot",
    "model_name",
    "response_model_name",
    "model_description",
    "prompt_tokens",
    "cached_input",
    "completion_tokens",
    "total_tokens",
    "time_cost",
    "request_id",
)


def _read(value: Any, *keys: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        return None
    for key in keys:
        if hasattr(value, key):
            return getattr(value, key)
    return None


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _usage_value(usage: Any, key: str) -> float:
    value = _finite_number(_read(usage, key))
    return max(0.0, value or 0.0)


def _has_usage(usage: Any) -> bool:
    if usage is None:
        return False
    return any(
        _read(usage, key) is not None
        for key in _USAGE_KEYS
    )


def _usage_total_tokens(usage: Any) -> float:
    explicit = _finite_number(_read(usage, "total_tokens"))
    if explicit is not None and explicit > 0:
        return explicit
    return _usage_value(usage, "prompt_tokens") + _usage_value(
        usage, "completion_tokens"
    )


def _usage_model_name(usage: Any) -> str:
    for key in (
        "model_name",
        "response_model_name",
        "model_description",
        "intent",
    ):
        value = _read(usage, key)
        if value:
            return str(value)
    return "Unknown"


def collect_report_summary(
    report: Any,
    wall_time_fallback_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Aggregate token/timing facts from an execution dump."""
    executions = _read(report, "executions")
    if not isinstance(executions, (list, tuple)):
        raise ValueError("collectReportSummary: report.executions must be an array")

    earliest: Optional[float] = None
    latest: Optional[float] = None
    model_call_count = 0
    model_call_time_ms = 0.0
    models: Dict[str, Dict[str, Any]] = {}

    def add_timestamp(value: Any) -> None:
        nonlocal earliest, latest
        timestamp = _finite_number(value)
        if timestamp is None:
            return
        earliest = timestamp if earliest is None else min(earliest, timestamp)
        latest = timestamp if latest is None else max(latest, timestamp)

    def add_usage(usage: Any) -> None:
        nonlocal model_call_count, model_call_time_ms
        if not _has_usage(usage):
            return
        model_name = _usage_model_name(usage)
        current = models.get(
            model_name,
            {
                "modelName": model_name,
                "callCount": 0,
                "promptTokens": 0,
                "cachedInputTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "modelCallTimeMs": 0,
            },
        )
        call_time_ms = _usage_value(usage, "time_cost")
        models[model_name] = {
            "modelName": model_name,
            "callCount": current["callCount"] + 1,
            "promptTokens": current["promptTokens"]
            + _usage_value(usage, "prompt_tokens"),
            "cachedInputTokens": current["cachedInputTokens"]
            + _usage_value(usage, "cached_input"),
            "completionTokens": current["completionTokens"]
            + _usage_value(usage, "completion_tokens"),
            "totalTokens": current["totalTokens"] + _usage_total_tokens(usage),
            "modelCallTimeMs": current["modelCallTimeMs"] + call_time_ms,
        }
        model_call_count += 1
        model_call_time_ms += call_time_ms

    for execution in executions:
        tasks = _read(execution, "tasks") or []
        for task in tasks:
            timing = _read(task, "timing") or {}
            add_timestamp(_read(timing, "start"))
            add_timestamp(_read(timing, "end"))
            add_usage(_read(task, "usage"))
            add_usage(_read(task, "searchAreaUsage", "search_area_usage"))

    model_summaries: List[Dict[str, Any]] = list(models.values())
    tokens = {
        "promptTokens": sum(item["promptTokens"] for item in model_summaries),
        "cachedInputTokens": sum(
            item["cachedInputTokens"] for item in model_summaries
        ),
        "completionTokens": sum(
            item["completionTokens"] for item in model_summaries
        ),
        "totalTokens": sum(item["totalTokens"] for item in model_summaries),
    }

    fallback = _finite_number(wall_time_fallback_ms)
    has_fallback = fallback is not None and fallback >= 0
    wall_time_ms: Optional[float] = None
    if earliest is not None and latest is not None:
        wall_time_ms = max(0.0, latest - earliest)
        wall_time_source = "task-timestamps"
    elif has_fallback:
        wall_time_ms = fallback
        wall_time_source = "fallback"
    else:
        wall_time_source = "unavailable"

    return {
        "timing": {
            "wallTimeMs": wall_time_ms,
            "wallTimeStart": earliest if wall_time_source == "task-timestamps" else None,
            "wallTimeEnd": latest if wall_time_source == "task-timestamps" else None,
            "wallTimeSource": wall_time_source,
            "modelCallTimeMs": model_call_time_ms,
            "modelCallCount": model_call_count,
        },
        "tokens": tokens,
        "models": model_summaries,
    }


__all__ = ["collect_report_summary"]
