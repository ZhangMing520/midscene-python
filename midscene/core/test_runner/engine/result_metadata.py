"""Phase/retry facts for report metadata (upstream engine/result-metadata.ts)."""

from typing import Any, Iterable, Mapping

from midscene.core.test_run_report import (
    TestRunReportPhaseResult,
    TestRunReportRetryDecision,
)


def phase_result(
    planned_step_count: int,
    steps: Iterable[Mapping[str, Any]],
) -> TestRunReportPhaseResult:
    step_list = list(steps)
    executed_step_count = len(
        [step for step in step_list if step.get("status") != "not-run"]
    )
    if planned_step_count == 0:
        status = "not-required"
    elif any(step.get("status") == "failed" for step in step_list):
        status = "failed"
    elif executed_step_count < planned_step_count:
        status = "not-run"
    else:
        status = "success"
    return {
        "plannedStepCount": planned_step_count,
        "executedStepCount": executed_step_count,
        "status": status,
    }


def decide_retry(options: Mapping[str, Any]) -> TestRunReportRetryDecision:
    """Facts at the retry boundary, separate from the eventual cleanup outcome."""
    if options.get("infrastructureError"):
        reason = "infrastructure-error"
    elif options.get("cleanupPending"):
        reason = "cleanup-pending"
    elif options.get("cleanupFailed"):
        reason = "cleanup-failed"
    elif options.get("operationPending"):
        reason = "operation-pending"
    elif options.get("fatalError"):
        reason = "fatal-error"
    elif options.get("interrupted"):
        reason = "interrupted"
    elif options.get("shouldStop"):
        reason = "bail"
    elif options.get("status") == "success":
        reason = "passed"
    elif options.get("attemptIndex", 0) >= options.get("retryCount", 0):
        reason = "budget-exhausted"
    else:
        reason = "attempt-failed"
    return {
        "scope": options["scope"],
        "retryCount": options.get("retryCount", 0),
        "attemptIndex": options.get("attemptIndex", 0),
        "decision": "retry" if reason == "attempt-failed" else "stop",
        "reason": reason,
    }


__all__ = ["decide_retry", "phase_result"]
