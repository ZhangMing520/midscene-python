"""Synced from upstream packages/core/tests/unit-test/report-markdown.test.ts."""

from pathlib import Path

import pytest

from midscene.core.report_markdown import (
    execution_to_markdown,
    report_to_markdown,
)
from midscene.core.screenshot_item import ScreenshotItem

_SNAPSHOT = (
    Path(__file__).parent
    / "__snapshots__"
    / "report-markdown.output.md"
)


def create_task(overrides=None):
    task = {
        "taskId": "task-1",
        "type": "Action Space",
        "subType": "Tap",
        "status": "finished",
        "param": {"locate": {"prompt": "Submit"}},
        "timing": {
            "start": 1710000000000,
            "end": 1710000000100,
            "cost": 100,
        },
    }
    if overrides:
        task.update(overrides)
    return task


def test_handles_single_execution_markdown_with_screenshot_file_links():
    """handles single execution markdown with screenshot file links"""
    screenshot = ScreenshotItem.create(
        "data:image/png;base64,Zm9v", 1710000000000
    )
    execution = {
        "logTime": 1710000000000,
        "name": "single execution",
        "tasks": [
            create_task(
                {
                    "uiContext": {
                        "screenshot": screenshot,
                        "shotSize": {"width": 1280, "height": 720},
                    },
                    "recorder": [
                        {
                            "type": "screenshot",
                            "ts": 1710000000050,
                            "timing": "after click",
                            "description": "Post-click state",
                            "screenshot": {
                                "type": "midscene_screenshot_ref",
                                "id": "shot-recorder-single",
                                "capturedAt": 1710000000050,
                                "mimeType": "image/png",
                                "storage": "file",
                                "path": "./screenshots/shot-recorder-single.png",
                            },
                        }
                    ],
                }
            )
        ],
    }

    result = execution_to_markdown(execution)
    markdown = result["markdown"]

    assert "# single execution" in markdown
    assert "Tap - Submit" in markdown
    assert "### Screenshots" in markdown
    assert (
        "- #1 type=ui-context, ts=2024-03-09T16:00:00.000Z, "
        "timing=ui-context" in markdown
    )
    assert "![task-1-ui-context](./screenshots/" in markdown
    assert "![task-1-after-click](./screenshots/" in markdown
    assert "timing=after click" in markdown
    assert "description=Post-click state" in markdown
    assert "Screen size: 1280 x 720" in markdown
    assert markdown.index("### Screenshots") < markdown.index(
        "![task-1-ui-context](./screenshots/"
    )
    assert len(result["attachments"]) == 2
    assert ".png" in result["attachments"][0]["suggestedFileName"]
    assert (
        f"./screenshots/{result['attachments'][0]['suggestedFileName']}"
        in markdown
    )


def test_merges_all_executions_into_one_markdown_and_keeps_file_snapshot():
    """merges all executions into one markdown and keeps file snapshot"""
    report = {
        "sdkVersion": "1.0.0",
        "groupName": "report-group",
        "modelBriefs": [],
        "executions": [
            {
                "logTime": 1710000000000,
                "name": "exec-1",
                "tasks": [
                    create_task(
                        {
                            "taskId": "task-1",
                            "uiContext": {
                                "screenshot": {
                                    "type": "midscene_screenshot_ref",
                                    "id": "shot-exec-1",
                                    "capturedAt": 1710000000000,
                                    "mimeType": "image/png",
                                    "storage": "file",
                                    "path": "./screenshots/shot-exec-1.png",
                                },
                                "shotSize": {"width": 1440, "height": 900},
                            },
                            "recorder": [
                                {
                                    "type": "screenshot",
                                    "ts": 1710000000060,
                                    "timing": "record-step-1",
                                    "screenshot": {
                                        "type": "midscene_screenshot_ref",
                                        "id": "shot-recorder-exec-1",
                                        "capturedAt": 1710000000060,
                                        "mimeType": "image/png",
                                        "storage": "file",
                                        "path": (
                                            "./screenshots/"
                                            "shot-recorder-exec-1.png"
                                        ),
                                    },
                                }
                            ],
                        }
                    )
                ],
            },
            {
                "logTime": 1710000000200,
                "name": "exec-2",
                "tasks": [
                    create_task(
                        {
                            "taskId": "task-2",
                            "subType": "Locate",
                            "output": {"element": {"center": [512, 333]}},
                            "uiContext": {
                                "screenshot": {
                                    "type": "midscene_screenshot_ref",
                                    "id": "shot-exec-2",
                                    "capturedAt": 1710000000200,
                                    "mimeType": "image/png",
                                    "storage": "file",
                                    "path": "./screenshots/shot-exec-2.png",
                                },
                                "shotSize": {"width": 1024, "height": 768},
                            },
                        }
                    )
                ],
            },
        ],
    }

    result = report_to_markdown(report)
    markdown = result["markdown"]

    assert "# report-group" in markdown
    assert "# exec-1" in markdown
    assert "# exec-2" in markdown
    assert "Suggested execution markdown files" not in markdown
    assert "timing=record-step-1" in markdown
    assert "Screen size: 1440 x 900" in markdown
    assert "Screen size: 1024 x 768" in markdown
    assert "Locate center: (512, 333)" in markdown
    assert len(result["attachments"]) == 3

    assert markdown == _SNAPSHOT.read_text(encoding="utf-8")


def test_uses_timing_fallback_fields_and_custom_screenshot_directory():
    """uses timing fallback fields and custom screenshot directory"""
    screenshot = ScreenshotItem.create(
        "data:image/png;base64,Zm9v", 1710000000000
    )
    execution = {
        "logTime": 1710000000000,
        "name": "fallback execution",
        "tasks": [
            create_task(
                {
                    "taskId": "task-fallback",
                    "timing": {
                        "callAiStart": 1710000000001,
                        "callAiEnd": 1710000000009,
                    },
                    "uiContext": {
                        "screenshot": screenshot,
                        "shotSize": {"width": 800, "height": 600},
                    },
                }
            )
        ],
    }

    result = execution_to_markdown(
        execution, {"screenshotBaseDir": "./shots"}
    )

    assert "./shots/" in result["markdown"]
    assert "Cost(ms): 8" in result["markdown"]
    assert "Screen size: 800 x 600" in result["markdown"]
    assert len(result["attachments"]) == 1


def test_preserves_restored_screenshot_source_refs_for_file_backed_export():
    """preserves restored screenshot source refs for file-backed export"""
    execution = {
        "logTime": 1710000000000,
        "name": "restored file screenshot",
        "tasks": [
            create_task(
                {
                    "uiContext": {
                        "screenshot": {
                            "base64": "./screenshots/original-shot.png",
                            "capturedAt": 1710000000000,
                            "sourceRef": {
                                "type": "midscene_screenshot_ref",
                                "id": "original-shot",
                                "capturedAt": 1710000000000,
                                "mimeType": "image/png",
                                "storage": "file",
                                "path": "./screenshots/original-shot.png",
                            },
                        }
                    }
                }
            )
        ],
    }

    result = execution_to_markdown(execution)

    assert len(result["attachments"]) == 1
    attachment = result["attachments"][0]
    assert attachment["id"] == "original-shot"
    assert (
        attachment["suggestedFileName"]
        == "execution-1-task-1-original-shot.png"
    )
    assert attachment["base64Data"] == "./screenshots/original-shot.png"
    assert attachment["sourceRef"]["path"] == "./screenshots/original-shot.png"
    assert (
        "./screenshots/execution-1-task-1-original-shot.png"
        in result["markdown"]
    )


def test_includes_model_metadata_token_usage_and_task_context_for_agent_analysis():
    """includes model metadata, token usage, and task context for agent analysis"""
    report = {
        "sdkVersion": "1.0.0",
        "groupName": "agent-ready-report",
        "modelBriefs": [
            {
                "intent": "planning",
                "name": "gpt-4o",
                "modelDescription": "vision planner",
            }
        ],
        "deviceType": "web",
        "executions": [
            {
                "logTime": 1710000000000,
                "name": "agent execution",
                "aiActContext": "Complete checkout.",
                "tasks": [
                    create_task(
                        {
                            "taskId": "task-agent-context",
                            "usage": {
                                "intent": "planning",
                                "model_name": "gpt-4o",
                                "model_description": "vision planner",
                                "prompt_tokens": 100,
                                "cached_input": 20,
                                "completion_tokens": 30,
                                "total_tokens": 130,
                                "time_cost": 456,
                                "request_id": "req-main",
                            },
                            "searchAreaUsage": {
                                "intent": "insight",
                                "model_name": "gpt-4o-mini",
                                "prompt_tokens": 10,
                                "completion_tokens": 3,
                                "total_tokens": 13,
                                "time_cost": 123,
                                "request_id": "req-search",
                            },
                            "output": {"result": "clicked"},
                            "log": {"note": "button matched"},
                            "thought": "Submit button is visible.",
                            "reasoning_content": (
                                "Clicking submit completes the form."
                            ),
                        }
                    )
                ],
            }
        ],
    }

    markdown = report_to_markdown(report)["markdown"]

    assert "## Model Info" in markdown
    assert "| planning | gpt-4o | vision planner |" in markdown
    assert "## Timing Summary" in markdown
    assert "| Elapsed Time | 100 |" in markdown
    assert "| Model Call Time | 579 |" in markdown
    assert "Total duration of all recorded model calls." in markdown
    assert "## Token Usage Summary" in markdown
    assert "Model Call Time(ms)" in markdown
    assert "| gpt-4o | 1 | 100 | 20 | 30 | 130 | 456 |" in markdown
    assert "| gpt-4o-mini | 1 | 10 | 0 | 3 | 13 | 123 |" in markdown
    assert "### Model Usage" in markdown
    assert "req-main" in markdown
    assert "req-search" in markdown
    assert "### AI Action Context" in markdown
    assert "Complete checkout." in markdown
    assert "### Param" in markdown
    assert '"prompt": "Submit"' in markdown
    assert "### Output" in markdown
    assert '"result": "clicked"' in markdown
    assert "### Log" in markdown
    assert '"note": "button matched"' in markdown
    assert "### Thought" in markdown
    assert "Submit button is visible." in markdown
    assert "### Reasoning Content" in markdown
    assert "Clicking submit completes the form." in markdown


def test_explains_the_elapsed_time_fallback_in_markdown():
    """explains the elapsed-time fallback in markdown"""
    report = {
        "sdkVersion": "1.0.0",
        "groupName": "fallback-timing-report",
        "modelBriefs": [],
        "executions": [
            {
                "logTime": 1710000000000,
                "name": "execution without task timing",
                "tasks": [create_task({"timing": None})],
            }
        ],
    }

    markdown = report_to_markdown(
        report, {"wallTimeFallbackMs": 2500}
    )["markdown"]

    assert "| Elapsed Time | 2500 |" in markdown
    assert (
        "Total elapsed duration reported by the enclosing test runner because "
        "task timestamps were unavailable." in markdown
    )


def test_falls_back_report_model_info_to_task_usage_when_model_briefs_are_missing():
    """falls back report model info to task usage when model briefs are missing"""
    report = {
        "sdkVersion": "1.0.0",
        "groupName": "usage-model-report",
        "modelBriefs": [],
        "executions": [
            {
                "logTime": 1710000000000,
                "name": "usage execution",
                "tasks": [
                    create_task(
                        {
                            "usage": {
                                "intent": "planning",
                                "model_name": "openai_qwen3.5-plus",
                                "model_description": "qwen3.5 mode",
                                "prompt_tokens": 100,
                                "completion_tokens": 20,
                            }
                        }
                    )
                ],
            }
        ],
    }

    markdown = report_to_markdown(report)["markdown"]

    assert "## Model Info" in markdown
    assert "| planning | openai_qwen3.5-plus | qwen3.5 mode |" in markdown
    assert "No report-level model metadata recorded" not in markdown


def test_handles_recorder_screenshots_stored_as_base64_strings():
    """handles recorder screenshots stored as base64 strings"""
    execution = {
        "logTime": 1710000000000,
        "name": "recorder string screenshot",
        "tasks": [
            create_task(
                {
                    "taskId": "task-recorder-string",
                    "uiContext": {
                        "screenshot": {
                            "base64": "data:image/png;base64,bWFpbg==",
                            "capturedAt": 1710000000000,
                        },
                        "shotSize": {"width": 800, "height": 600},
                    },
                    "recorder": [
                        {
                            "type": "screenshot",
                            "ts": 1710000000050,
                            "timing": "after action",
                            "screenshot": (
                                "data:image/png;base64,cmVjb3JkZXI="
                            ),
                        }
                    ],
                }
            )
        ],
    }

    result = execution_to_markdown(execution)

    assert "### Screenshots" in result["markdown"]
    assert "timing=ui-context" in result["markdown"]
    assert "timing=after action" in result["markdown"]
    assert len(result["attachments"]) == 2
    assert result["attachments"][0]["base64Data"] == (
        "data:image/png;base64,bWFpbg=="
    )
    assert result["attachments"][1]["base64Data"] == (
        "data:image/png;base64,cmVjb3JkZXI="
    )
    assert "recorder-1" in result["attachments"][1]["suggestedFileName"]
    assert (
        result["attachments"][1]["suggestedFileName"]
        != result["attachments"][0]["suggestedFileName"]
    )


def test_throws_with_invalid_input():
    """throws with invalid input"""
    with pytest.raises(ValueError) as execution_error:
        execution_to_markdown({})
    assert (
        "executionToMarkdown: execution.tasks must be an array"
        in str(execution_error.value)
    )

    with pytest.raises(ValueError) as report_error:
        report_to_markdown({"groupName": "bad"})
    assert (
        "reportToMarkdown: report.executions must be an array"
        in str(report_error.value)
    )


def test_gracefully_skips_tasks_without_screenshots():
    """gracefully skips tasks without screenshots"""
    execution = {
        "logTime": 1710000000000,
        "name": "no-screenshot-execution",
        "tasks": [create_task()],
    }

    result = execution_to_markdown(execution)

    assert "# no-screenshot-execution" in result["markdown"]
    assert "Tap - Submit" in result["markdown"]
    assert "Screen size: N/A" in result["markdown"]
    assert len(result["attachments"]) == 0
