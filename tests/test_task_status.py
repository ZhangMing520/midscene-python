"""Synced from upstream packages/core/tests/unit-test/task-status.test.ts."""

from midscene.core.dump.task_status import derive_case_status, derive_task_status


def test_treats_a_thrown_failed_task_as_failed():
    """treats a thrown / failed task as failed"""
    assert (
        derive_task_status(
            {
                "status": "failed",
                "errorMessage": "Assertion failed: button not visible",
            }
        )
        == "failed"
    )


def test_treats_a_finished_task_carrying_an_error_as_failed():
    """treats a finished task carrying an error as failed"""
    assert (
        derive_task_status(
            {"status": "finished", "error": {"name": "Error", "message": "x"}}
        )
        == "failed"
    )
    assert (
        derive_task_status({"status": "finished", "errorMessage": "boom"}) == "failed"
    )


def test_treats_a_finished_waitfor_with_falsy_output_as_a_warning():
    """treats a finished WaitFor with falsy output as a warning"""
    assert (
        derive_task_status(
            {"status": "finished", "subType": "WaitFor", "output": False}
        )
        == "warning"
    )


def test_treats_a_finished_assert_with_false_output_as_failed():
    """treats a finished Assert with false output as failed"""
    assert (
        derive_task_status({"status": "finished", "subType": "Assert", "output": False})
        == "failed"
    )


def test_treats_a_clean_finished_task_as_passed():
    """treats a clean finished task as passed"""
    assert derive_task_status({"status": "finished"}) == "passed"
    assert (
        derive_task_status({"status": "finished", "subType": "Assert", "output": True})
        == "passed"
    )


def test_passes_through_lifecycle_statuses():
    """passes through lifecycle statuses"""
    assert derive_task_status({"status": "pending"}) == "pending"
    assert derive_task_status({"status": "running"}) == "running"
    assert derive_task_status({"status": "cancelled"}) == "cancelled"


def test_returns_passed_when_every_task_passed():
    """returns passed when every task passed"""
    assert (
        derive_case_status(
            [{"tasks": [{"status": "finished"}, {"status": "finished"}]}]
        )
        == "passed"
    )


def test_returns_failed_when_any_task_failed():
    """returns failed when any task failed"""
    assert (
        derive_case_status(
            [
                {
                    "tasks": [
                        {"status": "finished"},
                        {"status": "failed", "errorMessage": "Assertion failed"},
                    ]
                }
            ]
        )
        == "failed"
    )


def test_does_not_fail_a_case_for_a_waitfor_warning_alone():
    """does not fail a case for a WaitFor warning alone"""
    assert (
        derive_case_status(
            [
                {
                    "tasks": [
                        {"status": "finished"},
                        {
                            "status": "finished",
                            "subType": "WaitFor",
                            "output": False,
                        },
                    ]
                }
            ]
        )
        == "passed"
    )


def test_handles_empty_task_less_executions():
    """handles empty / task-less executions"""
    assert derive_case_status([]) == "passed"
    assert derive_case_status([{}]) == "passed"
