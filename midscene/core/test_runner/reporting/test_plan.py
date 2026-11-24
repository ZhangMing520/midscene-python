"""Report-facing execution plan (upstream test-runner/reporting/test-plan.ts)."""

import copy
from typing import Any

from midscene.core.test_run_report import (
    TestRunReportCasePlan,
    TestRunReportDocumentPlan,
    TestRunReportPlannedStep,
)
from midscene.core.test_runner.parser.types import (
    CollectedWorkflowDocument,
    NormalizedStep,
)
from midscene.core.test_runner.reporting.sanitize import (
    sanitize_report_text,
    sanitize_report_value,
)


def _step_title(input_value: dict[str, Any]) -> str | None:
    candidate = (
        input_value.get("prompt")
        or input_value.get("script")
        or input_value.get("scenario")
        or input_value.get("title")
    )
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        prompt = candidate.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return None


def _build_steps(
    document: CollectedWorkflowDocument,
    items: list[NormalizedStep],
    phase: str,
    owner: str,
    default_timeout_ms: float | None,
) -> list[TestRunReportPlannedStep]:
    planned: list[TestRunReportPlannedStep] = []
    for step_index, step in enumerate(items):
        template_input = step.get("templateInput")
        input_value = (
            template_input if template_input is not None else step.get("input", {})
        )
        title = _step_title(input_value)
        timeout_ms = step.get("meta", {}).get("timeoutMs", default_timeout_ms)
        entry: TestRunReportPlannedStep = {
            "id": f"{document['documentId']}:{owner}:{phase}:{step_index}",
            "phase": phase,
            "stepIndex": step_index,
            "node": step.get("node"),
            "input": sanitize_report_value(input_value),
            "inputMode": "template" if template_input is not None else "resolved",
        }
        if title:
            entry["title"] = sanitize_report_text(title, 240)
        if timeout_ms is not None:
            entry["timeoutMs"] = timeout_ms
        if "continueOnError" in step.get("meta", {}):
            entry["continueOnError"] = step["meta"]["continueOnError"]
        planned.append(entry)
    return planned


def build_test_run_report_plan(
    document: CollectedWorkflowDocument,
    options: dict[str, Any] | None = None,
) -> TestRunReportDocumentPlan:
    options = options or {}
    default_timeout_ms = options.get("defaultTimeoutMs")
    selected_case_ids = options.get("selectedCaseIds")
    selected: set[str] = (
        set(selected_case_ids)
        if selected_case_ids is not None
        else {item["caseId"] for item in document["cases"]}
    )

    cases: list[TestRunReportCasePlan] = []
    for item in document["cases"]:
        definition = item["definition"]
        case_plan: TestRunReportCasePlan = {
            "caseId": item["caseId"],
            "name": definition.get("name"),
            "caseIndex": item["caseIndex"],
            "selected": item["caseId"] in selected,
            "tags": list(definition.get("tags") or []),
            "beforeEach": _build_steps(
                document,
                document["lifecycle"]["beforeEach"],
                "beforeEach",
                item["caseId"],
                default_timeout_ms,
            ),
            "steps": _build_steps(
                document,
                definition.get("steps", []),
                "steps",
                item["caseId"],
                default_timeout_ms,
            ),
            "afterEach": _build_steps(
                document,
                document["lifecycle"]["afterEach"],
                "afterEach",
                item["caseId"],
                default_timeout_ms,
            ),
        }
        if definition.get("onFailure"):
            case_plan["onFailure"] = definition["onFailure"]
        cases.append(case_plan)

    plan: TestRunReportDocumentPlan = {
        "documentId": document["documentId"],
        "sourcePath": document.get("sourcePath"),
        "retry": options.get("retry") or {"scope": "case", "count": 0},
        "beforeAll": _build_steps(
            document,
            document["lifecycle"]["beforeAll"],
            "beforeAll",
            "document",
            default_timeout_ms,
        ),
        "cases": cases,
        "afterAll": _build_steps(
            document,
            document["lifecycle"]["afterAll"],
            "afterAll",
            "document",
            default_timeout_ms,
        ),
    }
    if document.get("sourceYaml"):
        plan["sourceYaml"] = copy.deepcopy(document["sourceYaml"])
    return plan


__all__ = ["build_test_run_report_plan"]
