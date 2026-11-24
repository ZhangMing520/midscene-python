"""Test run health summaries (upstream core/src/test-run-health.ts)."""

from typing import Any

TEST_RUN_CASE_HEALTH_STATUSES = ("passed", "retry-passed", "failed", "not-run")


def _case_attempts(test_case: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = test_case.get("attempts")
    if attempts is not None:
        return list(attempts)
    run = test_case.get("run")
    return [run] if run else []


def classify_test_run_case(test_case: dict[str, Any]) -> str:
    """Classify one logical Case using the retry evidence available to its caller."""
    if test_case.get("status") == "not-run":
        return "not-run"
    if test_case.get("status") == "failed":
        return "failed"
    attempts = _case_attempts(test_case)
    last_attempt_index = (attempts[-1].get("attemptIndex") or 0) if attempts else 0
    retried = (
        (test_case.get("retryCount") or 0) > 0
        or last_attempt_index > 0
        or len(attempts) > 1
        or (attempts[0].get("status") == "failed" if attempts else False)
    )
    return "retry-passed" if retried else "passed"


def calculate_test_run_health(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    failed = 0
    not_run = 0
    first_passed = 0
    passed_after_retry = 0
    for test_case in cases:
        classification = classify_test_run_case(test_case)
        if classification == "passed":
            passed += 1
            first_passed += 1
        elif classification == "retry-passed":
            passed += 1
            passed_after_retry += 1
        elif classification == "failed":
            failed += 1
        else:
            not_run += 1

    total = len(cases)
    executed = total - not_run
    return {
        "total": total,
        "executed": executed,
        "passed": passed,
        "failed": failed,
        "notRun": not_run,
        "firstPassed": first_passed,
        "passedAfterRetry": passed_after_retry,
        "finalPassRate": 0 if executed == 0 else passed / executed,
        "firstPassRate": 0 if executed == 0 else first_passed / executed,
    }


__all__ = [
    "TEST_RUN_CASE_HEALTH_STATUSES",
    "calculate_test_run_health",
    "classify_test_run_case",
]
