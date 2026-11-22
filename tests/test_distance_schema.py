"""Synced from upstream packages/core/tests/unit-test/distance-schema.test.ts."""

import pytest

from midscene.core.common import parse_action_param
from midscene.core.device import DeviceAction


def _agent(model_family: str = "gpt-5", **options):
    from midscene.core.agent.agent import Agent
    from midscene.core.agent.agent_options import AgentOptions
    from tests.core_helpers import MockInterface

    config = {
        "MIDSCENE_MODEL_NAME": "mock-model",
        "MIDSCENE_MODEL_API_KEY": "sk-test",
        "MIDSCENE_MODEL_BASE_URL": "https://example.com/v1",
        "MIDSCENE_MODEL_FAMILY": model_family,
    }
    return Agent(MockInterface(), AgentOptions(model_config=config, **options))


def test_uses_metadata_rather_than_action_parameter_names_and_leaves_durations_untouched():
    action = DeviceAction(
        name="Scroll", description="", distance_fields=["distance"]
    )

    parsed = parse_action_param(
        {"distance": 100},
        action,
        {
            "distanceUnit": "model-input-image-pixel",
            "shrunkShotToLogicalRatio": 2,
        },
    )

    assert parsed == {"distance": 50}
    assert parse_action_param({"x": 1}, None) is None


def test_marks_all_builtin_core_distance_fields():
    from midscene.core.device import (
        build_android_action_space,
        build_web_action_space,
        scale_action_distances,
    )

    action_space = build_web_action_space() + build_android_action_space()
    for name in ("Scroll", "Swipe", "Pinch"):
        definition = next(a for a in action_space if a.name == name)
        assert definition.distance_fields == ["distance"], name
        scaled = scale_action_distances({"distance": 100}, definition, 2.0)
        assert scaled["distance"] == 50

    definition = next(a for a in action_space if a.name == "Tap")
    param = {"distance": 100}
    assert scale_action_distances(param, definition, 2.0) is param


def test_survives_number_refinements_descriptions_and_optional_nullable_default_wrappers():
    from midscene.core.device import build_web_action_space, scale_action_distances

    definition = next(a for a in build_web_action_space() if a.name == "Scroll")
    for bad in (-1, float("nan"), float("inf"), True, "100"):
        with pytest.raises(ValueError):
            scale_action_distances({"distance": bad}, definition, 2.0)
    with pytest.raises(ValueError):
        scale_action_distances({"distance": 10}, definition, 0)


def test_does_not_scale_a_missing_distance_default():
    from midscene.core.device import build_web_action_space, scale_action_distances

    definition = next(a for a in build_web_action_space() if a.name == "Scroll")
    assert scale_action_distances({}, definition, 2.0) == {}
    assert scale_action_distances({"distance": None}, definition, 2.0) == {
        "distance": None
    }


@pytest.mark.asyncio
async def test_converts_positions_and_distances_with_the_same_ratio():
    agent = _agent()
    action = {
        "type": "Scroll",
        "param": {"direction": "down", "distance": 100},
    }
    await agent._execute_planning_action(action, distance_ratio=2.0)

    direction, distance, _ = agent.interface.scrolled[-1]
    assert direction == "down"
    assert distance == 50
    assert action["param"]["distance"] == 50


@pytest.mark.asyncio
async def test_keeps_explicit_api_distances_and_model_visual_distances_invariant_at_shrink():
    agent = _agent()
    cached = {
        "yamlWorkflow": (
            "- type: Scroll\n"
            "  direction: down\n"
            "  distance: 100\n"
        )
    }
    assert await agent._replay_cached_plan(cached) is True
    assert agent.interface.scrolled[-1][1] == 100

    await agent.ai_scroll(scroll_param={"direction": "down", "distance": 100})
    assert agent.interface.scrolled[-1][1] == 100


def test_writes_device_unit_distances_to_yaml_without_changing_the_plan():
    import yaml

    from midscene.core.ai_model.workflows import build_yaml_flow_from_plans
    from midscene.core.device import build_web_action_space

    flow = build_yaml_flow_from_plans(
        [{"type": "Scroll", "param": {"direction": "down", "distance": 100}}],
        build_web_action_space(),
        2.0,
    )
    parsed = yaml.safe_load(flow)
    assert parsed[0]["distance"] == 50
    assert parsed[0]["direction"] == "down"
