"""Token usage metrics (upstream agent/metrics.ts)."""

from typing import Any


def _usage_field(usage: Any, name: str, default: Any = None) -> Any:
    if isinstance(usage, dict):
        return usage.get(name, default)
    return getattr(usage, name, default)


def _empty_bucket() -> dict[str, int]:
    return {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "calls": 0,
    }


def _add_to_bucket(
    buckets: dict[str, dict[str, int]],
    key: str,
    prompt: int,
    completion: int,
    total: int,
) -> None:
    bucket = buckets.setdefault(key, _empty_bucket())
    bucket["promptTokens"] += prompt
    bucket["completionTokens"] += completion
    bucket["totalTokens"] += total
    bucket["calls"] += 1


class MetricsCollector:
    """Pure accumulator for AI usage records (upstream MetricsCollector)."""

    def __init__(self) -> None:
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cached_input = 0
        self.total_time_cost_ms = 0
        self.calls = 0
        self.by_intent: dict[str, dict[str, int]] = {}
        self.by_model: dict[str, dict[str, int]] = {}

    def add(self, usage: Any) -> None:
        """Accumulate one usage record; every call counts as one call."""
        prompt = int(_usage_field(usage, "prompt_tokens", 0) or 0)
        completion = int(_usage_field(usage, "completion_tokens", 0) or 0)
        total = int(_usage_field(usage, "total_tokens", 0) or 0)

        self.total_prompt_tokens += prompt
        self.total_completion_tokens += completion
        self.total_tokens += total
        self.total_cached_input += int(_usage_field(usage, "cached_input", 0) or 0)
        self.total_time_cost_ms += int(_usage_field(usage, "time_cost", 0) or 0)
        self.calls += 1

        _add_to_bucket(
            self.by_intent,
            _usage_field(usage, "intent") or "unknown",
            prompt,
            completion,
            total,
        )
        _add_to_bucket(
            self.by_model,
            _usage_field(usage, "model_name") or "unknown",
            prompt,
            completion,
            total,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return an independent snapshot of the accumulated metrics."""
        return {
            "totalPromptTokens": self.total_prompt_tokens,
            "totalCompletionTokens": self.total_completion_tokens,
            "totalTokens": self.total_tokens,
            "totalCachedInput": self.total_cached_input,
            "totalTimeCostMs": self.total_time_cost_ms,
            "calls": self.calls,
            "byIntent": {key: dict(bucket) for key, bucket in self.by_intent.items()},
            "byModel": {key: dict(bucket) for key, bucket in self.by_model.items()},
        }

    def reset(self) -> None:
        """Clear all accumulated state."""
        type(self).__init__(self)


def record_usage_metrics(
    metrics: dict[str, dict[str, int]],
    intent: str,
    usage: dict[str, Any] | None,
) -> None:
    """Accumulate one usage record into the per-intent buckets."""
    if not usage:
        return
    bucket = metrics.setdefault(
        intent, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        bucket[key] += int(usage.get(key) or 0)


__all__ = ["MetricsCollector", "record_usage_metrics"]
