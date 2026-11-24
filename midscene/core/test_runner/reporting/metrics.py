"""Test-run report metrics (upstream reporting/metrics.ts)."""

import math
from collections.abc import Iterable
from typing import Any

from midscene.core.report_stats import collect_report_summary
from midscene.core.test_run_report import TestRunReportMetrics

_NUMERIC_KEYS = (
    "modelCallCount",
    "modelTimeMs",
    "promptTokens",
    "cachedInputTokens",
    "completionTokens",
    "totalTokens",
)
_MODEL_KEYS = (
    "callCount",
    "modelCallTimeMs",
    "promptTokens",
    "cachedInputTokens",
    "completionTokens",
    "totalTokens",
)
_USAGE_KEYS = (
    "intent",
    "slot",
    "model_name",
    "modelName",
    "response_model_name",
    "model_description",
    "prompt_tokens",
    "promptTokens",
    "cached_input",
    "cachedInputTokens",
    "completion_tokens",
    "completionTokens",
    "total_tokens",
    "totalTokens",
    "time_cost",
    "timeCost",
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


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _has_usage(usage: Any) -> bool:
    if usage is None:
        return False
    return any(_read(usage, key) is not None for key in _USAGE_KEYS)


def _state(known: int, missing: bool) -> str:
    if not missing:
        return "complete"
    return "partial" if known > 0 else "unknown"


def collect_test_run_report_metrics(report: Any) -> TestRunReportMetrics:
    """A captured execution can still lack provider usage or contain a live request."""
    summary = collect_report_summary(report)
    executions = _read(report, "executions") or []
    tasks: list[Any] = []
    for execution in executions:
        tasks.extend(_read(execution, "tasks") or [])

    def task_usage(task: Any) -> Any:
        return _read(task, "usage")

    def task_search_usage(task: Any) -> Any:
        return _read(task, "searchAreaUsage", "search_area_usage")

    usages: list[Any] = []
    live = False
    unrecorded = False
    for task in tasks:
        for usage in (task_usage(task), task_search_usage(task)):
            if _has_usage(usage):
                usages.append(usage)
        timing = _read(task, "timing") or {}
        started = _read(timing, "callAiStart", "call_ai_start", "start") is not None
        status = _read(task, "status")
        if started and status in ("pending", "running"):
            live = True
        if started and not _has_usage(task_usage(task)):
            unrecorded = True

    known_times = sum(
        1 for usage in usages if _number(_read(usage, "time_cost", "timeCost"))
    )
    known_tokens = sum(
        1
        for usage in usages
        if _number(_read(usage, "total_tokens", "totalTokens"))
        or (
            _number(_read(usage, "prompt_tokens", "promptTokens"))
            and _number(_read(usage, "completion_tokens", "completionTokens"))
        )
    )

    reasons: list[str] = []
    if live:
        reasons.append("A model request was still running when usage was captured.")
    if unrecorded:
        reasons.append("A model request started but its usage was not recorded.")
    if known_times < len(usages):
        reasons.append("Some model usage records do not include request duration.")
    if known_tokens < len(usages):
        reasons.append("Some model usage records do not include token counts.")
    if any(
        not _number(_read(usage, "prompt_tokens", "promptTokens")) for usage in usages
    ):
        reasons.append("Some model usage records do not include input token counts.")
    if any(
        not _number(_read(usage, "completion_tokens", "completionTokens"))
        for usage in usages
    ):
        reasons.append("Some model usage records do not include output token counts.")

    fields = {
        "modelCallCount": _state(
            summary["timing"]["modelCallCount"], live or unrecorded
        ),
        "modelTimeMs": _state(
            known_times, live or unrecorded or known_times < len(usages)
        ),
        "promptTokens": _state(
            sum(
                1
                for usage in usages
                if _number(_read(usage, "prompt_tokens", "promptTokens"))
            ),
            live
            or unrecorded
            or any(
                not _number(_read(usage, "prompt_tokens", "promptTokens"))
                for usage in usages
            ),
        ),
        "completionTokens": _state(
            sum(
                1
                for usage in usages
                if _number(_read(usage, "completion_tokens", "completionTokens"))
            ),
            live
            or unrecorded
            or any(
                not _number(_read(usage, "completion_tokens", "completionTokens"))
                for usage in usages
            ),
        ),
        "totalTokens": _state(
            known_tokens, live or unrecorded or known_tokens < len(usages)
        ),
    }
    model_call_count = summary["timing"]["modelCallCount"]
    result: TestRunReportMetrics = {
        "modelCallCount": model_call_count,
        "modelTimeMs": summary["timing"]["modelCallTimeMs"],
        **summary["tokens"],
        "collection": {
            "status": (
                ("partial" if model_call_count > 0 else "unknown")
                if reasons
                else "complete"
            ),
            "expectedExecutionCount": 0,
            "capturedExecutionCount": 0,
            "reasons": reasons,
            "fields": fields,
        },
    }
    if summary["models"]:
        result["models"] = summary["models"]
    return result


def sum_test_run_report_metrics(
    values: Iterable[TestRunReportMetrics],
    missing_reasons: Iterable[str] = (),
) -> TestRunReportMetrics:
    """Add usage facts without treating missing screenshots as missing model calls."""
    value_list = list(values)
    missing = list(missing_reasons)
    total: TestRunReportMetrics = {
        "modelCallCount": 0,
        "modelTimeMs": 0,
        "promptTokens": 0,
        "cachedInputTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
    }
    models: dict[str, dict[str, Any]] = {}
    for value in value_list:
        for key in _NUMERIC_KEYS:
            total[key] = total.get(key, 0) + value.get(key, 0)
        for model in value.get("models") or []:
            name = model.get("modelName")
            previous = models.get(name)
            if previous is None:
                models[name] = dict(model)
            else:
                for key in _MODEL_KEYS:
                    previous[key] = previous.get(key, 0) + model.get(key, 0)
    if models:
        total["models"] = list(models.values())

    fields: dict[str, str] = {}
    for field in (
        "modelCallCount",
        "modelTimeMs",
        "totalTokens",
        "promptTokens",
        "completionTokens",
    ):
        states = [
            (value.get("collection") or {}).get("fields", {}).get(field)
            or (value.get("collection") or {}).get("status")
            or "complete"
            for value in value_list
        ]
        if missing:
            states.append("unknown")
        if all(state == "complete" for state in states):
            fields[field] = "complete"
        elif all(state == "unknown" for state in states):
            fields[field] = "unknown"
        else:
            fields[field] = "partial"

    if all(state == "complete" for state in fields.values()):
        status = "complete"
    elif all(state == "unknown" for state in fields.values()):
        status = "unknown"
    else:
        status = "partial"

    reasons: list[str] = []
    for value in value_list:
        for reason in (value.get("collection") or {}).get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)
    for reason in missing:
        if reason not in reasons:
            reasons.append(reason)

    total["collection"] = {
        "status": status,
        "fields": fields,
        "expectedExecutionCount": 0,
        "capturedExecutionCount": 0,
        "reasons": reasons,
    }
    return total


__all__ = ["collect_test_run_report_metrics", "sum_test_run_report_metrics"]
