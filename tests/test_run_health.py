"""Synced from upstream packages/core/tests/unit-test/test-run-health.test.ts."""

from midscene.core.test_run_health import (
    calculate_test_run_health,
    classify_test_run_case,
)


def _test_case(status, attempts=None, retry_count=0):
    return {"status": status, "attempts": attempts or [], "retryCount": retry_count}


def test_uses_one_retry_classification_for_case_and_projected_document_retries():
    assert (
        classify_test_run_case(
            _test_case("success", [{"attemptIndex": 0, "status": "success"}])
        )
        == "passed"
    )
    assert (
        classify_test_run_case(
            _test_case(
                "success",
                [
                    {"attemptIndex": 0, "status": "failed"},
                    {"attemptIndex": 1, "status": "success"},
                ],
            )
        )
        == "retry-passed"
    )
    assert (
        classify_test_run_case(
            _test_case("success", [{"attemptIndex": 1, "status": "success"}])
        )
        == "retry-passed"
    )
    assert (
        classify_test_run_case(
            _test_case("success", [{"attemptIndex": 0, "status": "success"}], 1)
        )
        == "retry-passed"
    )
    assert classify_test_run_case(_test_case("failed")) == "failed"
    assert classify_test_run_case(_test_case("not-run")) == "not-run"


def test_calculates_counts_and_rates_from_the_same_logical_cases():
    assert calculate_test_run_health(
        [
            _test_case("success", [{"attemptIndex": 0, "status": "success"}]),
            _test_case(
                "success",
                [
                    {"attemptIndex": 0, "status": "failed"},
                    {"attemptIndex": 1, "status": "success"},
                ],
            ),
            _test_case("failed", [{"attemptIndex": 0, "status": "failed"}]),
            _test_case("not-run"),
        ]
    ) == {
        "total": 4,
        "executed": 3,
        "passed": 2,
        "failed": 1,
        "notRun": 1,
        "firstPassed": 1,
        "passedAfterRetry": 1,
        "finalPassRate": 2 / 3,
        "firstPassRate": 1 / 3,
    }
