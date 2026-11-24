"""Synced from upstream
``packages/core/tests/unit-test/workflows/recorder-generation/markdown.test.ts``."""

import base64
import io
from typing import Any
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from midscene.core.ai_model.workflows.recorder_generation import (
    create_recorder_markdown_replay_prompt,
    generate_recorder_markdown_replay,
    limit_screenshot_assets_for_markdown_replay,
    normalize_generated_markdown,
    prepare_screenshot_assets_for_markdown_replay,
)

SCREENSHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"


def _mock_events() -> list:
    return [
        {
            "type": "navigation",
            "timestamp": 1000,
            "url": "https://example.com",
            "title": "Example Page",
            "screenshotAfter": SCREENSHOT,
            "pageInfo": {"width": 1280, "height": 720},
            "hashId": "nav-1",
        },
        {
            "type": "click",
            "timestamp": 2000,
            "semantic": {
                "source": "aiDescribe",
                "status": "ready",
                "elementDescription": "Primary action button",
            },
            "screenshotWithBox": SCREENSHOT,
            "pageInfo": {"width": 1280, "height": 720},
            "hashId": "click-1",
        },
    ]


def _png(width: int, height: int) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 80, 160)).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _prompt_text(prompt) -> str:
    content = prompt[1]["content"]
    return "\n".join(part["text"] for part in content if part["type"] == "text")


def test_normalizes_generated_markdown_code_fences():
    assert normalize_generated_markdown("```md\n# Title\n```") == "# Title\n"
    assert normalize_generated_markdown("# Plain") == "# Plain\n"


def test_limit_screenshot_assets_omits_oversized_payloads():
    big = {"dataUrl": "x" * 700_000, "eventIndex": 0, "eventHashId": "a"}
    small = {"dataUrl": "y" * 100, "eventIndex": 1, "eventHashId": "b"}
    kept = limit_screenshot_assets_for_markdown_replay([big, small])
    assert kept == [small]


def test_compresses_oversized_screenshots_to_jpeg_before_model_generation():
    small = _png(300, 200)
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
    assert kept[0]["dataUrl"] == small
    assert kept[0]["mimeType"] == "image/png"
    assert kept[0]["base64Data"] == "keep"

    resized = prepare_screenshot_assets_for_markdown_replay(
        [
            {
                "dataUrl": _png(1600, 900),
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


def test_logs_image_compression_failures_before_retaining_the_original_asset():
    asset = {
        "dataUrl": SCREENSHOT,
        "eventIndex": 0,
        "eventHashId": "nav-1",
        "eventType": "navigation",
        "mimeType": "image/png",
    }
    with (
        patch(
            "midscene.core.ai_model.workflows.recorder_generation.markdown._image_info_of_base64",
            side_effect=RuntimeError("bad png"),
        ),
        patch(
            "midscene.core.ai_model.workflows.recorder_generation.markdown.logger"
        ) as mock_logger,
    ):
        prepared = prepare_screenshot_assets_for_markdown_replay([asset])

    assert prepared == [asset]
    logged = mock_logger.debug.call_args[0][0]
    assert "failed to compress screenshot asset; keeping original" in logged
    assert "nav-1" in logged


def test_creates_a_compact_ai_act_focused_prompt_with_recorder_data():
    prompt = create_recorder_markdown_replay_prompt(
        {
            "target": {
                "platformId": "android",
                "label": "emulator-5554",
                "values": {"deviceId": "emulator-5554"},
            },
            "events": _mock_events(),
            "testName": "Replay workflow",
            "language": "English",
        }
    )

    text = _prompt_text(prompt)

    assert "await agent.aiAct(markdownReplayPrompt)" in text
    assert "- Platform: android" in text
    assert "Target block:" in text
    assert "Replay goal:" in text
    assert "Reproduce the recorded user workflow exactly." in text
    assert "Do not invent alternative navigation paths." in text
    assert (
        "Do not target a placeholder character, typed character, caret, or "
        "inner text fragment inside the field." in text
    )
    assert "For scroll events, preserve the recorded scroll region" in text
    assert (
        "keep that region in the Markdown step instead of generalizing it to "
        "the whole page" in text
    )
    assert (
        "Do not include screenshots, image syntax, image paths, or "
        "reference-image names" in text
    )
    assert (
        "agent.aiAct(markdownReplayPrompt), which accepts text only and cannot "
        "receive attached images" in text
    )
    assert "Never write Markdown image syntax such as ![step context](...)" in text
    assert "./screenshots/... paths" in text
    assert '"events"' in text
    assert '"screenshots"' in text
    assert '"eventCounts"' not in text
    assert '"clickDescriptions"' not in text
    assert '"inputDescriptions"' not in text
    assert "Write all human-readable Markdown instructions in English." in text
    assert '"screenshotRef": "screenshot-1"' in text
    assert "./screenshots/event-001-navigation.png" not in text
    assert len(text) < 8000


def test_preserves_specific_semantic_scroll_regions_in_the_markdown_prompt_data():
    nav = _mock_events()[0]
    prompt = create_recorder_markdown_replay_prompt(
        {
            "target": {
                "platformId": "web",
                "label": "Web",
                "values": {"url": "https://example.com/docs"},
            },
            "events": [
                nav,
                {
                    "type": "scroll",
                    "actionType": "Scroll",
                    "timestamp": 2000,
                    "value": "down 545",
                    "semantic": {
                        "source": "recorderAI",
                        "status": "ready",
                        "elementDescription": "left navigation panel",
                        "replayInstruction": (
                            'Scroll the page/region with description "left '
                            'navigation panel" by value "down 545" until '
                            '"component links in the navigation list" is visible.'
                        ),
                        "actionSummary": (
                            "Scroll left navigation panel toward component "
                            "links in the navigation list"
                        ),
                        "confidence": "high",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "scroll-left-nav",
                },
                {
                    "type": "click",
                    "actionType": "Tap",
                    "timestamp": 3000,
                    "semantic": {
                        "source": "recorderAI",
                        "status": "ready",
                        "elementDescription": "link in the left navigation panel",
                        "replayInstruction": (
                            'Tap on the element described as "link in the '
                            'left navigation panel".'
                        ),
                        "actionSummary": "Tap link in the left navigation panel",
                        "confidence": "high",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "click-left-nav-link",
                },
            ],
            "testName": "Replay workflow",
            "maxScreenshots": 0,
        }
    )

    text = _prompt_text(prompt)

    assert '"hashId": "scroll-left-nav"' in text
    assert '"elementDescription": "left navigation panel"' in text
    assert 'Scroll the page/region with description \\"left navigation panel\\"' in text
    assert '"nextActionDescription": "Tap link in the left navigation panel"' in text


def test_includes_sequence_context_for_neighboring_input_events():
    nav = _mock_events()[0]
    prompt = create_recorder_markdown_replay_prompt(
        {
            "target": {
                "platformId": "web",
                "label": "Web",
                "values": {"url": "https://example.com"},
            },
            "events": [
                nav,
                {
                    "type": "input",
                    "actionType": "Input",
                    "timestamp": 2000,
                    "value": "alpha",
                    "semantic": {
                        "source": "heuristic",
                        "status": "ready",
                        "elementDescription": "input field in Example Page",
                        "confidence": "low",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "input-1",
                },
                {
                    "type": "click",
                    "actionType": "Tap",
                    "timestamp": 2500,
                    "semantic": {
                        "source": "aiDescribe",
                        "status": "ready",
                        "elementDescription": "secondary field",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "click-between-inputs",
                },
                {
                    "type": "input",
                    "actionType": "Input",
                    "timestamp": 3000,
                    "value": "123456",
                    "semantic": {
                        "source": "heuristic",
                        "status": "ready",
                        "elementDescription": "input field in Example Page",
                        "confidence": "low",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "input-2",
                },
            ],
            "testName": "Replay workflow",
        }
    )

    text = _prompt_text(prompt)

    assert '"inputIndex": 1' in text
    assert '"inputIndex": 2' in text
    assert '"typedText": "alpha"' in text
    assert '"typedText": "123456"' in text
    assert "For input events, enter event.typedText/event.value exactly" in text
    assert '"hasNeighborInput": true' in text
    assert '"neighborInputValues"' in text
    assert '"previousInputDescription"' in text
    assert '"nextActionDescription": "secondary field"' in text


def test_includes_next_action_context_for_field_focus_clicks():
    nav = _mock_events()[0]
    prompt = create_recorder_markdown_replay_prompt(
        {
            "target": {
                "platformId": "web",
                "label": "Web",
                "values": {"url": "https://example.com"},
            },
            "events": [
                nav,
                {
                    "type": "click",
                    "actionType": "Tap",
                    "timestamp": 2000,
                    "semantic": {
                        "source": "aiDescribe",
                        "status": "ready",
                        "elementDescription": ('the character "code" inside the field'),
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "click-focus",
                },
                {
                    "type": "input",
                    "actionType": "Input",
                    "timestamp": 2100,
                    "value": "002937",
                    "semantic": {
                        "source": "aiDescribe",
                        "status": "ready",
                        "elementDescription": "verification code input field",
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "input-code",
                },
            ],
            "testName": "Replay workflow",
        }
    )

    text = _prompt_text(prompt)

    assert '"hashId": "click-focus"' in text
    assert '"nextActionDescription": "verification code input field"' in text


def test_omits_oversized_screenshot_payloads_from_markdown_generation_prompts():
    prompt = create_recorder_markdown_replay_prompt(
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
                    "screenshotAfter": ("data:image/png;base64," + "a" * 700_000),
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "nav-oversized",
                }
            ],
            "testName": "Replay workflow",
        }
    )

    content = prompt[1]["content"]
    text = _prompt_text(prompt)
    assert not any(part["type"] == "image" for part in content)
    assert "./screenshots/event-001-navigation.png" not in text
    assert '"hashId": "nav-oversized"' in text


def test_omits_fallback_audit_chains_before_building_markdown_prompts():
    long_error = "verify failed: " + "x" * 5000
    prompt = create_recorder_markdown_replay_prompt(
        {
            "target": {
                "platformId": "web",
                "label": "Web",
                "values": {"url": "https://example.com"},
            },
            "events": [
                {
                    "type": "click",
                    "actionType": "Tap",
                    "timestamp": 1000,
                    "semantic": {
                        "source": "recorderAI",
                        "status": "ready",
                        "elementDescription": "Submit button",
                        "error": long_error,
                        "fallbackFrom": {
                            "source": "aiDescribe",
                            "status": "failed",
                            "error": long_error,
                            "fallbackFrom": {
                                "source": "heuristic",
                                "status": "failed",
                                "error": long_error,
                            },
                        },
                    },
                    "pageInfo": {"width": 1280, "height": 720},
                    "hashId": "click-with-long-semantic",
                }
            ],
            "testName": "Replay workflow",
            "maxScreenshots": 0,
        }
    )

    text = _prompt_text(prompt)
    assert '"error": "verify failed:' in text
    assert "[truncated" in text
    assert '"fallbackFrom"' not in text
    assert '"source": "heuristic"' not in text
    assert len(text) < 20_000


@pytest.mark.asyncio
async def test_compresses_oversized_screenshots_before_model_generation():
    large = _png(1024, 512)
    captured: dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "# Replay workflow", "usage": None}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.markdown.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_recorder_markdown_replay(
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
                        "screenshotAfter": large,
                        "pageInfo": {"width": 1024, "height": 512},
                        "hashId": "large-navigation",
                    }
                ],
                "testName": "Replay workflow",
            },
            Mock(),
        )

    user_content = captured["prompt"][1]["content"]
    image_part = next(part for part in user_content if part["type"] == "image")
    assert image_part["url"].startswith("data:image/jpeg;base64,")
    with Image.open(
        io.BytesIO(base64.b64decode(image_part["url"].split(",", 1)[1]))
    ) as image:
        assert image.size == (768, 384)


@pytest.mark.asyncio
async def test_generates_raw_markdown_replay_content():
    captured: dict[str, Any] = {}
    raw = (
        "```markdown\n# Replay workflow\n\n## Steps\n1. Open page\n"
        "2. Tap on the element described as \"content card titled 'daily "
        "featured story' in the main content grid\".\n```"
    )

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": raw, "usage": None}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.markdown.call_ai_with_string_response",
        new=fake_call,
    ):
        result = await generate_recorder_markdown_replay(
            {
                "target": {
                    "platformId": "web",
                    "label": "Web",
                    "values": {"url": "https://example.com"},
                },
                "events": _mock_events(),
                "testName": "Replay workflow",
            },
            Mock(),
        )

    assert result == (
        "# Replay workflow\n\n## Steps\n1. Open page\n"
        "2. Tap on the element described as \"content card titled 'daily "
        "featured story' in the main content grid\".\n"
    )
    assert captured["prompt"][0]["role"] == "system"
    assert "must not contain image references" in captured["prompt"][0]["content"]


@pytest.mark.asyncio
async def test_wraps_markdown_generation_errors():
    async def fake_call(prompt, runtime):
        raise RuntimeError("down")

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.markdown.call_ai_with_string_response",
        new=fake_call,
    ):
        with pytest.raises(RuntimeError) as exc:
            await generate_recorder_markdown_replay(
                {
                    "target": {
                        "platformId": "web",
                        "label": "Web",
                        "values": {"url": "https://example.com"},
                    },
                    "events": _mock_events(),
                    "testName": "Replay workflow",
                },
                Mock(),
            )
    assert "Failed to generate recorder Markdown replay" in str(exc.value)
