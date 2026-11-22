"""Synced from upstream packages/core/tests/unit-test/task-service-dump.test.ts."""

from midscene.core.dump.task_service_dump import (
    get_task_search_area,
    get_task_service_dump,
)

_SERVICE_DUMP = {
    "type": "locate",
    "taskInfo": {
        "durationMs": 100,
        "searchArea": {"left": 10, "top": 20, "width": 300, "height": 200},
    },
}


def test_reads_the_wrapped_service_dump_from_task_logs():
    """reads the wrapped service dump from task logs"""
    task = {"log": {"dump": _SERVICE_DUMP}}

    assert get_task_service_dump(task) is _SERVICE_DUMP
    assert get_task_search_area(task) == _SERVICE_DUMP["taskInfo"]["searchArea"]


def test_prefers_the_explicit_task_search_area_when_present():
    """prefers the explicit task searchArea when present"""
    task = {
        "searchArea": {"left": 1, "top": 2, "width": 3, "height": 4},
        "log": {"dump": _SERVICE_DUMP},
    }

    assert get_task_search_area(task) == {
        "left": 1,
        "top": 2,
        "width": 3,
        "height": 4,
    }


def test_ignores_direct_service_dump_logs():
    """ignores direct service dump logs"""
    task = {"log": _SERVICE_DUMP}

    assert get_task_service_dump(task) is None
