"""Synced from upstream packages/core/tests/unit-test/runner-test-plan.test.ts."""

from typing import Any

from midscene.core.test_runner.reporting.test_plan import build_test_run_report_plan


def _step(
    node: str, input_value: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    return {"node": node, "input": input_value, "meta": meta}


def _document() -> dict[str, Any]:
    return {
        "documentId": "document",
        "projectId": "project",
        "sourcePath": "map.yaml",
        "lifecycle": {
            "beforeAll": [
                _step("setup", {"prompt": "Open debugger"}, {"continueOnError": False})
            ],
            "beforeEach": [
                _step("setup", {"prompt": "Reset map"}, {"continueOnError": False})
            ],
            "afterEach": [],
            "afterAll": [],
        },
        "cases": [
            {
                "caseId": f"case-{case_index}",
                "projectId": "project",
                "sourcePath": "map.yaml",
                "caseIndex": case_index,
                "definition": {
                    "name": f"Map {case_index}",
                    "tags": ["slow" if case_index else "smoke"],
                    "steps": [
                        _step(
                            "body",
                            {
                                "prompt": {"prompt": "Preview map"},
                                "apiKey": "secret",
                            },
                            {"timeoutMs": 30, "continueOnError": True},
                        )
                    ],
                },
            }
            for case_index in (0, 1)
        ],
    }


def test_snapshots_all_phases_and_selection_without_retaining_mutable_inputs():
    original = _document()
    plan = build_test_run_report_plan(
        original,
        {
            "selectedCaseIds": ["case-0"],
            "defaultTimeoutMs": 100,
            "retry": {"scope": "document", "count": 2},
        },
    )
    assert plan["retry"] == {"scope": "document", "count": 2}
    assert [item["selected"] for item in plan["cases"]] == [True, False]
    assert plan["beforeAll"][0]["timeoutMs"] == 100
    step = plan["cases"][0]["steps"][0]
    assert step["title"] == "Preview map"
    assert step["timeoutMs"] == 30
    assert step["continueOnError"] is True
    assert step["input"]["value"]["prompt"] == {"prompt": "Preview map"}
    assert step["input"]["value"]["apiKey"] == "secret"
    assert (
        plan["cases"][0]["beforeEach"][0]["id"]
        != plan["cases"][1]["beforeEach"][0]["id"]
    )
    assert (
        build_test_run_report_plan(original)["cases"][0]["steps"][0]["id"] == step["id"]
    )
    original["cases"][0]["definition"]["steps"][0]["input"]["prompt"] = "changed"
    assert plan["cases"][0]["steps"][0]["input"]["value"]["prompt"] == {
        "prompt": "Preview map"
    }
