"""Synced from upstream
``packages/core/tests/unit-test/workflows/recorder-generation/yaml.test.ts``."""

from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest


def _events() -> List[Dict[str, Any]]:
    return [
        {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
        {"type": "click", "description": "search box", "timestamp": 2},
        {"type": "input", "description": "search box", "value": "shoes", "timestamp": 3},
        {"type": "scroll", "timestamp": 4},
    ]


def test_creates_default_web_target_from_navigation():
    from midscene.core.ai_model.workflows.recorder_generation import (
        create_default_web_target,
    )

    target = create_default_web_target(_events(), {})
    assert target["platformId"] == "web"
    assert target["values"]["url"] == "https://shop.example"


def test_normalizes_generated_yaml_code_fences():
    from midscene.core.ai_model.workflows.recorder_generation import (
        normalize_generated_yaml,
    )

    assert normalize_generated_yaml("```yaml\n- type: Tap\n```") == "- type: Tap\n"
    assert normalize_generated_yaml("- type: Tap") == "- type: Tap\n"


@pytest.mark.asyncio
async def test_generates_recorder_yaml_from_recorded_events():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_yaml_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "```yaml\nweb:\n  url: https://shop.example\ntasks: []\n```"}

    runtime = Mock()
    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_ai_with_string_response",
        new=fake_call,
    ):
        yaml_out = await generate_yaml_test(_events(), {}, runtime)

    assert yaml_out.startswith("web:\n")
    system_prompt = captured["prompt"][0]["content"]
    assert "aiTap" in system_prompt
    user_prompt = captured["prompt"][1]["content"]
    assert "https://shop.example" in user_prompt
    assert "Return ONLY the raw YAML content" in user_prompt


@pytest.mark.asyncio
async def test_wraps_yaml_generation_errors():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_yaml_test,
    )

    async def fake_call(prompt, runtime):
        raise RuntimeError("model down")

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_ai_with_string_response",
        new=fake_call,
    ):
        with pytest.raises(RuntimeError) as exc:
            await generate_yaml_test(_events(), {}, Mock())
    assert "Failed to generate recorder YAML test" in str(exc.value)
