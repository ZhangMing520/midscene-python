"""Synced from upstream packages/core/tests/unit-test/report-stats.test.ts."""

import pytest

from midscene.core.report_stats import collect_report_summary
from midscene.core.test_runner.reporting.metrics import (
    collect_test_run_report_metrics,
    sum_test_run_report_metrics,
)

_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_input",
    "time_cost",
    "model_name",
    "model_description",
    "response_model_name",
    "intent",
    "slot",
    "request_id",
)


def create_usage(**overrides):
    usage = dict.fromkeys(_USAGE_KEYS)
    usage.update(overrides)
    return usage


def create_task(**overrides):
    task = {"taskId": "task", "type": "Log", "status": "finished"}
    task.update(overrides)
    return task


def create_report(tasks):
    return {"executions": [{"logTime": 100, "name": "execution", "tasks": tasks}]}


def test_retains_per_model_usage_through_metric_aggregation_without_double_counting_cached_input():
    """retains per-model usage through metric aggregation without double-counting cached input"""

    def collect(model):
        return collect_test_run_report_metrics(
            create_report(
                [
                    create_task(
                        usage=create_usage(
                            model_name=model,
                            prompt_tokens=100,
                            completion_tokens=20,
                            cached_input=80,
                            total_tokens=120,
                            time_cost=10,
                        )
                    )
                ]
            )
        )

    first = collect("planning")
    total = sum_test_run_report_metrics([first, first, collect("insight")])

    assert total["totalTokens"] == 360
    assert total["cachedInputTokens"] == 240
    assert total["models"][0]["modelName"] == "planning"
    assert total["models"][0]["callCount"] == 2
    assert total["models"][0]["totalTokens"] == 240
    assert total["models"][1]["modelName"] == "insight"
    assert total["models"][1]["callCount"] == 1
    assert total["models"][1]["totalTokens"] == 120
    assert first["models"][0]["totalTokens"] == 120


def test_distinguishes_missing_provider_fields_from_actual_zero_usage():
    """distinguishes missing provider fields from actual zero usage"""
    missing = collect_test_run_report_metrics(
        create_report([create_task(usage=create_usage(model_name="model"))])
    )
    assert missing["collection"]["status"] == "partial"
    assert missing["collection"]["fields"]["modelCallCount"] == "complete"
    assert missing["collection"]["fields"]["modelTimeMs"] == "unknown"
    assert missing["collection"]["fields"]["totalTokens"] == "unknown"

    zero = collect_test_run_report_metrics(
        create_report(
            [
                create_task(
                    usage=create_usage(model_name="model", total_tokens=0, time_cost=0)
                )
            ]
        )
    )
    assert zero["modelCallCount"] == 1
    assert zero["modelTimeMs"] == 0
    assert zero["totalTokens"] == 0
    assert zero["collection"]["status"] == "partial"
    assert zero["collection"]["fields"]["totalTokens"] == "complete"
    assert zero["collection"]["fields"]["promptTokens"] == "unknown"
    assert zero["collection"]["fields"]["completionTokens"] == "unknown"

    assert (
        collect_test_run_report_metrics(create_report([create_task()]))["collection"][
            "status"
        ]
        == "complete"
    )


def test_marks_live_and_unrecorded_model_requests_as_incomplete_without_estimating_usage():
    """marks live and unrecorded model requests as incomplete without estimating usage"""
    unknown = collect_test_run_report_metrics(
        create_report(
            [create_task(status="failed", timing={"start": 1, "callAiStart": 2})]
        )
    )
    assert unknown["modelCallCount"] == 0
    assert unknown["totalTokens"] == 0
    assert unknown["collection"]["status"] == "unknown"

    partial = collect_test_run_report_metrics(
        create_report(
            [
                create_task(
                    usage=create_usage(model_name="model", total_tokens=7, time_cost=10)
                ),
                create_task(status="running", timing={"start": 0, "callAiStart": 1}),
            ]
        )
    )
    assert partial["modelCallCount"] == 1
    assert partial["totalTokens"] == 7
    assert partial["collection"]["status"] == "partial"
    assert partial["collection"]["fields"]["modelCallCount"] == "partial"
    assert partial["collection"]["fields"]["modelTimeMs"] == "partial"
    assert partial["collection"]["fields"]["totalTokens"] == "partial"


def test_keeps_usage_complete_for_a_pending_device_task_with_no_model_request():
    """keeps usage complete for a pending device task with no model request"""
    collection = collect_test_run_report_metrics(
        create_report([create_task(status="running", type="Action")])
    )["collection"]
    assert collection["status"] == "complete"
    assert collection["fields"]["modelCallCount"] == "complete"
    assert collection["fields"]["modelTimeMs"] == "complete"
    assert collection["fields"]["totalTokens"] == "complete"


def test_aggregates_elapsed_time_model_call_time_and_tokens_with_search_area_calls_attributed_to_their_own_models():
    """aggregates elapsed time, model call time, and tokens with search-area calls attributed to their own models"""
    report = create_report(
        [
            create_task(
                taskId="task-1",
                timing={"start": 100, "end": 300},
                usage=create_usage(
                    model_name="alpha",
                    prompt_tokens=10,
                    cached_input=2,
                    completion_tokens=3,
                    total_tokens=13,
                    time_cost=80,
                ),
                searchAreaUsage=create_usage(
                    model_name="beta",
                    prompt_tokens=4,
                    completion_tokens=1,
                    time_cost=30,
                ),
            ),
            create_task(
                taskId="task-2",
                timing={"start": 250, "end": 500},
                usage=create_usage(
                    model_name="alpha",
                    prompt_tokens=5,
                    completion_tokens=2,
                    time_cost=90,
                ),
            ),
            create_task(
                taskId="task-3",
                timing={"start": 150, "end": 450},
                searchAreaUsage=create_usage(
                    model_name="gamma",
                    prompt_tokens=7,
                    completion_tokens=1,
                    time_cost=20,
                ),
            ),
        ]
    )

    assert collect_report_summary(report) == {
        "timing": {
            "wallTimeMs": 400,
            "wallTimeStart": 100,
            "wallTimeEnd": 500,
            "wallTimeSource": "task-timestamps",
            "modelCallTimeMs": 220,
            "modelCallCount": 4,
        },
        "tokens": {
            "promptTokens": 26,
            "cachedInputTokens": 2,
            "completionTokens": 7,
            "totalTokens": 33,
        },
        "models": [
            {
                "modelName": "alpha",
                "callCount": 2,
                "promptTokens": 15,
                "cachedInputTokens": 2,
                "completionTokens": 5,
                "totalTokens": 20,
                "modelCallTimeMs": 170,
            },
            {
                "modelName": "beta",
                "callCount": 1,
                "promptTokens": 4,
                "cachedInputTokens": 0,
                "completionTokens": 1,
                "totalTokens": 5,
                "modelCallTimeMs": 30,
            },
            {
                "modelName": "gamma",
                "callCount": 1,
                "promptTokens": 7,
                "cachedInputTokens": 0,
                "completionTokens": 1,
                "totalTokens": 8,
                "modelCallTimeMs": 20,
            },
        ],
    }


def test_uses_the_elapsed_time_fallback_only_when_task_timestamps_are_unavailable():
    """uses the elapsed-time fallback only when task timestamps are unavailable"""
    no_timing = collect_report_summary(
        create_report([create_task()]), wall_time_fallback_ms=1234
    )
    with_timing = collect_report_summary(
        create_report([create_task(timing={"start": 20, "end": 70})]),
        wall_time_fallback_ms=1234,
    )

    assert no_timing["timing"]["wallTimeMs"] == 1234
    assert no_timing["timing"]["wallTimeSource"] == "fallback"
    assert with_timing["timing"]["wallTimeMs"] == 50
    assert with_timing["timing"]["wallTimeStart"] == 20
    assert with_timing["timing"]["wallTimeEnd"] == 70
    assert with_timing["timing"]["wallTimeSource"] == "task-timestamps"


def test_reports_unavailable_elapsed_time_and_zero_model_time_when_no_data_exists():
    """reports unavailable elapsed time and zero model time when no data exists"""
    assert collect_report_summary(create_report([])) == {
        "timing": {
            "wallTimeMs": None,
            "wallTimeStart": None,
            "wallTimeEnd": None,
            "wallTimeSource": "unavailable",
            "modelCallTimeMs": 0,
            "modelCallCount": 0,
        },
        "tokens": {
            "promptTokens": 0,
            "cachedInputTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
        },
        "models": [],
    }


def test_throws_when_executions_are_not_an_array():
    """throws when executions are not an array"""
    with pytest.raises(
        ValueError, match="collectReportSummary: report.executions must be an array"
    ):
        collect_report_summary({"executions": None})
