"""Token usage metrics (upstream agent/metrics.ts)."""

from typing import Any, Dict, Optional


def record_usage_metrics(
    metrics: Dict[str, Dict[str, int]],
    intent: str,
    usage: Optional[Dict[str, Any]],
) -> None:
    """Accumulate one usage record into the per-intent buckets."""
    if not usage:
        return
    bucket = metrics.setdefault(
        intent, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        bucket[key] += int(usage.get(key) or 0)
