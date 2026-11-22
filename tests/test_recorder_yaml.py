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


def _mock_events() -> List[Dict[str, Any]]:
    return [
        {
            "type": "navigation",
            "timestamp": 1000,
            "url": "https://example.com",
            "title": "Example Page",
            "pageInfo": {"width": 1280, "height": 720},
            "hashId": "nav-1",
        },
        {
            "type": "click",
            "timestamp": 2000,
            "semantic": {
                "source": "aiDescribe",
                "status": "ready",
                "elementDescription": "Login button",
            },
            "pageInfo": {"width": 1280, "height": 720},
            "hashId": "click-1",
        },
    ]


@pytest.mark.asyncio
async def test_adds_a_language_instruction_when_generating_yaml():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_yaml_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "yaml-content"}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_yaml_test(
            _mock_events(),
            {"testName": "Recorded session", "language": "Chinese"},
            Mock(),
        )

    user_message = captured["prompt"][1]
    assert "Write all human-readable YAML content in Chinese." in user_message["content"]


@pytest.mark.asyncio
async def test_uses_the_same_language_instruction_for_streaming_yaml_generation():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_yaml_test_stream,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime, options):
        captured["prompt"] = prompt
        return {"content": "yaml-content", "usage": None}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_generative_ai",
        new=fake_call,
    ):
        result = await generate_yaml_test_stream(
            _mock_events(),
            {"stream": True, "onChunk": lambda chunk: None, "language": "English"},
            Mock(),
        )

    assert result["isStreamed"] is True
    user_message = captured["prompt"][1]
    assert "Write all human-readable YAML content in English." in user_message["content"]


@pytest.mark.asyncio
async def test_preserves_non_web_recorder_targets_when_generating_yaml():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_recorder_yaml_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": 'computer:\n  displayId: "2"\n'}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_recorder_yaml_test(
            {
                "target": {
                    "platformId": "computer",
                    "label": "DELL U2720Q",
                    "values": {"displayId": "2"},
                },
                "events": [
                    {
                        "type": "click",
                        "source": "studio-preview",
                        "actionType": "Click",
                        "semantic": {
                            "source": "aiDescribe",
                            "status": "ready",
                            "elementDescription": "Use documentation link",
                        },
                        "elementRect": {"x": 73, "y": 1071},
                        "pageInfo": {"width": 1080, "height": 1920},
                        "timestamp": 1000,
                        "hashId": "computer-click",
                    }
                ],
                "testName": "Computer recording",
                "language": "Chinese",
            },
            Mock(),
        )

    user_message = captured["prompt"][1]
    assert (
        "Preserve this exact top-level target platform: computer"
        in user_message["content"]
    )
    assert 'computer:\n  displayId: "2"' in user_message["content"]
    assert "Use documentation link" in user_message["content"]


@pytest.mark.asyncio
async def test_marks_screenshot_event_relationships_in_recorder_yaml_prompts():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_recorder_yaml_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": 'web:\n  url: "https://example.com"\n'}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.yaml.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_recorder_yaml_test(
            {
                "target": {
                    "platformId": "web",
                    "label": "Web",
                    "values": {"url": "https://example.com"},
                },
                "events": [
                    {
                        "type": "navigation",
                        "timestamp": 1000,
                        "url": "https://example.com",
                        "title": "Example Page",
                        "screenshotAfter": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ",
                        "pageInfo": {"width": 1280, "height": 720},
                        "hashId": "nav-1",
                    },
                    {
                        "type": "click",
                        "timestamp": 2000,
                        "semantic": {
                            "source": "aiDescribe",
                            "status": "ready",
                            "elementDescription": "Login button",
                        },
                        "screenshotWithBox": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSK",
                        "pageInfo": {"width": 1280, "height": 720},
                        "hashId": "click-1",
                    },
                ],
                "maxScreenshots": 2,
            },
            Mock(),
        )

    prompt_parts = []
    for message in captured["prompt"]:
        content = message["content"]
        if isinstance(content, list):
            prompt_parts.extend(
                part["text"] for part in content if part["type"] == "text"
            )
        else:
            prompt_parts.append(content)
    prompt_text = "\n".join(prompt_parts)

    assert "Screenshot assets:" in prompt_text
    assert '"eventHashId": "nav-1"' in prompt_text
    assert (
        "Screenshot asset for event #1: ./screenshots/event-001-navigation.png"
        in prompt_text
    )
    assert '"screenshotPath"' in prompt_text
