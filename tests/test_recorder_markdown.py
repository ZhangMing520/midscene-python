"""Synced from upstream
``packages/core/tests/unit-test/workflows/recorder-generation/markdown.test.ts``."""

import base64
import io
import json
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest
from PIL import Image


def _events():
    return [
        {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
        {"type": "click", "description": "search box", "timestamp": 2},
        {"type": "input", "description": "search box", "value": "shoes", "timestamp": 3},
    ]


def test_normalizes_generated_markdown_code_fences():
    from midscene.core.ai_model.workflows.recorder_generation import (
        normalize_generated_markdown,
    )

    assert normalize_generated_markdown("```md\n# Title\n```") == "# Title\n"
    assert normalize_generated_markdown("# Plain") == "# Plain\n"


def test_omits_oversized_screenshot_payloads_from_markdown_generation_prompts():
    from midscene.core.ai_model.workflows.recorder_generation import (
        limit_screenshot_assets_for_markdown_replay,
    )

    big = {"dataUrl": "x" * 700_000, "eventIndex": 0, "eventHashId": "a"}
    small = {"dataUrl": "y" * 100, "eventIndex": 1, "eventHashId": "b"}
    kept = limit_screenshot_assets_for_markdown_replay([big, small])
    # the oversized asset is dropped, the small one kept
    assert kept == [small]


def test_compresses_oversized_screenshots_to_jpeg_before_model_generation():
    from midscene.core.ai_model.workflows.recorder_generation import (
        prepare_screenshot_assets_for_markdown_replay,
    )

    def png(width, height):
        buffer = io.BytesIO()
        Image.new("RGBA", (width, height), (255, 0, 0, 0)).save(buffer, "PNG")
        return "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode()

    small = png(300, 200)
    kept = prepare_screenshot_assets_for_markdown_replay(
        [
            {
                "dataUrl": small,
                "eventIndex": 0,
                "eventHashId": "a",
                "mimeType": "image/png",
                "base64Data": "keep",
            }
        ]
    )
    # re-encoding a small PNG to JPEG blurs the UI text the model reads and
    # leaves mimeType/base64Data describing a different image
    assert kept[0]["dataUrl"] == small
    assert kept[0]["mimeType"] == "image/png"
    assert kept[0]["base64Data"] == "keep"

    resized = prepare_screenshot_assets_for_markdown_replay(
        [
            {
                "dataUrl": png(1600, 900),
                "eventIndex": 1,
                "eventHashId": "b",
                "mimeType": "image/png",
                "base64Data": "old",
            }
        ]
    )[0]
    assert resized["dataUrl"].startswith("data:image/jpeg;base64,")
    assert resized["mimeType"] == "image/jpeg"
    assert resized["base64Data"] == resized["dataUrl"].split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(resized["base64Data"]))) as image:
        assert max(image.size) == 768


def test_creates_a_compact_ai_act_focused_prompt_with_recorder_data():
    from midscene.core.ai_model.workflows.recorder_generation import (
        create_recorder_markdown_replay_prompt,
        prepare_event_summary,
    )

    events = [
        {
            "type": "click",
            "description": "div.k9x2",
            "semantic": {
                "source": "aiDescribe",
                "status": "ready",
                "elementDescription": "the blue cart button",
            },
        }
    ]
    summary = prepare_event_summary(events, {})

    def payload_for(assets):
        prompt = create_recorder_markdown_replay_prompt(
            {"testName": "t", "target": {"platformId": "web"}, "events": events},
            summary,
            assets,
        )
        text = prompt[1]["content"][0]["text"]
        return json.loads(
            text.split("Recorder data:\n", 1)[1].split("\n\nImportant:", 1)[0]
        )

    entry = payload_for(
        [
            {
                "eventIndex": 0,
                "eventHashId": summary["events"][0]["hashId"],
                "eventType": "click",
                "dataUrl": "data:image/jpeg;base64,AA",
            }
        ]
    )["screenshots"][0]
    # upstream resolves the label through the semantic description; the raw
    # recorder css path is noise for the model
    assert entry["description"] == "the blue cart button"

    # an asset from a stale recording must not fail the whole generation
    stale = payload_for(
        [
            {
                "eventIndex": 99,
                "eventHashId": "gone",
                "eventType": "click",
                "dataUrl": "data:image/jpeg;base64,AA",
            }
        ]
    )["screenshots"][0]
    assert stale["description"] is None
    assert stale["eventIndex"] == 99


def test_prompt_structure_and_screenshot_refs():
    from midscene.core.ai_model.workflows.recorder_generation import (
        create_recorder_markdown_replay_prompt,
        prepare_event_summary,
    )

    events = _events()
    target = {
        "platformId": "web",
        "label": "Web",
        "values": {"url": "https://shop.example"},
    }
    summary = prepare_event_summary(events, {})
    assets = [
        {
            "eventIndex": 1,
            "eventHashId": summary["events"][1]["hashId"],
            "eventType": "click",
            "dataUrl": "data:image/jpeg;base64,AAA",
            "relativePath": "shot-1.jpeg",
        }
    ]
    input_payload = {"testName": "checkout", "target": target, "events": events}
    prompt = create_recorder_markdown_replay_prompt(input_payload, summary, assets)

    # system role
    assert prompt[0]["role"] == "system"
    assert "agent.aiAct" in prompt[0]["content"]

    # user content carries the prompt text and one screenshot pair
    user_content = prompt[1]["content"]
    text_part = user_content[0]["text"]
    assert "screenshot-1" in text_part
    assert "Required structure:" in text_part
    assert "# checkout" in text_part
    assert "Never write Markdown image syntax" in text_part
    # image follows its label
    assert user_content[1]["text"].startswith("screenshot-1 for event #2")
    assert user_content[2]["type"] == "image"


@pytest.mark.asyncio
async def test_generates_raw_markdown_replay_content():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_markdown_replay,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "```md\n# checkout\n## Steps\n1. tap search\n```"}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.markdown.call_ai_with_string_response",
        new=fake_call,
    ):
        result = await generate_markdown_replay(_events(), {}, Mock())

    assert result.startswith("# checkout\n")
    system_prompt = captured["prompt"][0]["content"]
    assert "must not contain image references" in system_prompt


@pytest.mark.asyncio
async def test_wraps_markdown_generation_errors():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_markdown_replay,
    )

    async def fake_call(prompt, runtime):
        raise RuntimeError("down")

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.markdown.call_ai_with_string_response",
        new=fake_call,
    ):
        with pytest.raises(RuntimeError) as exc:
            await generate_markdown_replay(_events(), {}, Mock())
    assert "Failed to generate recorder Markdown replay" in str(exc.value)
