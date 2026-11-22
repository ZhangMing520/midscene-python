"""Synced from upstream packages/core/tests/unit-test/prompt/prompt.test.ts."""

from midscene.core.ai_model.model_adapter.default_insight_protocol import (
    create_default_insight_protocol,
)
from midscene.core.ai_model.models.registry import get_model_adapter
from midscene.core.ai_model.prompt.insight import (
    build_insight_system_prompt,
    extract_data_query_prompt,
)
from midscene.core.ai_model.prompt.planning import (
    build_standard_planning_system_prompt,
)
from midscene.core.device import build_web_action_space


def test_planning_renders_the_default_midscene_protocol():
    adapter = get_model_adapter("qwen3-vl")
    prompt = build_standard_planning_system_prompt(
        action_space=build_web_action_space(),
        planning_protocol=adapter.planning_protocol,
        include_locate_in_planning=True,
        locate_prompt_spec=adapter.locate_result_codec.prompt_spec,
    )

    assert "<planning>" in prompt
    assert "Supporting actions list" in prompt
    assert "type: Tap" in prompt or "- type: Tap" in prompt
    assert "<action-type>" in prompt
    assert "Multi-turn Conversation Example" in prompt
    assert "bbox_2d" in prompt


def test_build_insight_system_prompt():
    prompt = build_insight_system_prompt(create_default_insight_protocol())

    assert "DATA_DEMAND" in prompt
    assert "data-json" in prompt
    assert "<observation>" in prompt


def test_extract_element_by_extract_data_prompt():
    prompt = extract_data_query_prompt("a login page", {"title": "string"})

    assert "<PageDescription>" in prompt
    assert "a login page" in prompt
    assert "<DATA_DEMAND>" in prompt
