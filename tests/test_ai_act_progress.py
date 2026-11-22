"""Synced from upstream packages/core/tests/unit-test/ai-act-progress.test.ts."""

import pytest

from midscene.core.agent.progress.ai_act_progress import (
    create_ai_act_action_reporter,
    extract_progress_action,
)


def _action_task(param, sub_type="Tap"):
    return {"type": "Action Space", "subType": sub_type, "param": param}


def test_preserves_the_resolved_center_despite_conflicting_model_coordinates():
    """preserves the resolved center despite conflicting model coordinates"""
    action = extract_progress_action(
        _action_task(
            {
                "locate": {
                    "description": "submit",
                    "center": [10.25, 20.75],
                    "locatedPixelResult": {"center": [100, 200]},
                    "point": [300, 400],
                    "bbox": [0, 0, 1000, 1000],
                }
            }
        )
    )

    assert action["name"] == "Tap"
    assert action["target"] == "submit"
    assert list(action["point"]) == [10.25, 20.75]


_UNRESOLVED_LOCATORS = [
    {"locatedPixelResult": {"center": [10, 20]}},
    {"point": [10, 20]},
    {"bbox": [0, 0, 100, 100]},
    {"rect": {"left": 0, "top": 0, "width": 100, "height": 100}},
    {"center": [float("nan"), 20], "point": [10, 20], "bbox": [0, 0, 100, 100]},
    {"center": [10], "locatedPixelResult": {"center": [10, 20]}},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("locate", _UNRESOLVED_LOCATORS)
async def test_does_not_publish_unresolved_locator(locate):
    """does not publish unresolved locator %j"""
    task = _action_task({"locate": locate})
    assert extract_progress_action(task) is None

    emitted = []

    async def emit(phase, data):
        emitted.append((phase, data))

    reporter = create_ai_act_action_reporter(1, 3, emit)
    await reporter({"kind": "start", "task": task})
    assert emitted == []


@pytest.mark.asyncio
async def test_publishes_resolved_action_lifecycle_events_with_the_same_fractional_center():
    """publishes resolved action lifecycle events with the same fractional center"""
    task = _action_task(
        {"locate": {"description": "submit", "center": [10.25, 20.75]}}
    )
    emitted = []

    async def emit(phase, data):
        emitted.append((phase, data))

    reporter = create_ai_act_action_reporter(1, 3, emit)
    await reporter({"kind": "start", "task": task})
    await reporter({"kind": "finish", "task": task})

    assert [phase for phase, _ in emitted] == [
        "plan_action",
        "action_running",
        "action_done",
    ]
    for _, data in emitted:
        assert data["action"]["name"] == "Tap"
        assert data["action"]["target"] == "submit"
        assert list(data["action"]["point"]) == [10.25, 20.75]


def test_continues_reporting_actions_without_locator_parameters():
    """continues reporting actions without locator parameters"""
    assert extract_progress_action(_action_task({"timeMs": 100}, "Sleep")) == {
        "name": "Sleep",
        "param": {"timeMs": 100},
    }
