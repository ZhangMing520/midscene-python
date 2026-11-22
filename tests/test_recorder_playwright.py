"""Synced from upstream
``packages/core/tests/unit-test/workflows/recorder-generation/playwright.test.ts``."""

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


def test_validate_events_should_throw_for_empty_events_array():
    from midscene.core.ai_model.workflows.recorder_generation import validate_events

    with pytest.raises(ValueError):
        validate_events([])
    with pytest.raises(ValueError):
        validate_events([{"timestamp": 1}])


def test_create_event_counts_should_create_accurate_event_counts():
    from midscene.core.ai_model.workflows.recorder_generation import (
        create_event_counts,
    )

    counts = create_event_counts(_events())
    assert counts["navigation"] == 1
    assert counts["click"] == 1
    assert counts["input"] == 1
    assert counts["scroll"] == 1
    assert counts["total"] == 4


def test_process_events_for_llm_should_extract_relevant_event_data():
    from midscene.core.ai_model.workflows.recorder_generation import (
        process_events_for_llm,
    )

    events = [
        {
            "type": "click",
            "description": "raw desc",
            "semantic": {
                "source": "aiDescribe",
                "status": "ready",
                "elementDescription": "the blue cart button",
                "replayInstruction": "click the cart",
            },
        }
    ]
    processed = process_events_for_llm(events)
    assert processed[0]["description"] == "the blue cart button"
    assert processed[0]["value"] == "click the cart"


@pytest.mark.asyncio
async def test_generate_playwright_test():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "```typescript\nimport { test } from '@playwright/test';\n```"}

    events = [
        {"type": "navigation", "url": "https://shop.example", "timestamp": 1},
        {"type": "click", "description": "buy", "timestamp": 2},
    ]
    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        result = await generate_playwright_test(
            events, {"testName": "buy-flow"}, Mock()
        )

    assert result.startswith("import { test }")
    user_prompt = captured["prompt"][1]["content"]
    assert "@midscene/web/playwright" in user_prompt
    assert "https://shop.example" in user_prompt
    assert "Return ONLY the raw Playwright test code" in user_prompt


@pytest.mark.asyncio
async def test_playwright_summary_options():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    events = [{"type": "click", "timestamp": 1}]
    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            events,
            {"viewportSize": {"width": 800, "height": 600}, "waitForNetworkIdleTimeout": 3000},
            Mock(),
        )
    summary_text = captured["prompt"][1]["content"]
    assert '"viewportSize"' in summary_text
    assert "800" in summary_text
    assert "3000" in summary_text


@pytest.mark.asyncio
async def test_create_message_content_should_include_screenshots_when_provided():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    events = [{"type": "click", "timestamp": 1}]
    shots = [{"eventIndex": 0, "dataUrl": "data:image/png;base64,AA"}]
    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(events, {"screenshotAssets": shots}, Mock())

    # upstream createMessageContent keeps the intro, the prompt and the
    # shots in one user turn; a second turn reorders the context
    assert len(captured["prompt"]) == 2
    content = captured["prompt"][1]["content"]
    assert content[0]["text"].startswith("Here are screenshots")
    assert "Generate a Playwright test" in content[1]["text"]
    assert content[2]["type"] == "text" and content[3]["type"] == "image"


@pytest.mark.asyncio
async def test_playwright_normalizes_falsy_option_defaults():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        # an empty YAML option leaves these as None/0, and a model reading
        # "waitForNetworkIdle": null drops the wait from the generated test
        await generate_playwright_test(
            [{"type": "click", "timestamp": 1}],
            {"waitForNetworkIdle": None, "waitForNetworkIdleTimeout": 0},
            Mock(),
        )
    text = captured["prompt"][1]["content"]
    assert '"waitForNetworkIdle": true' in text
    assert '"waitForNetworkIdleTimeout": 2000' in text


@pytest.mark.asyncio
async def test_playwright_empty_response_raises():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    async def fake_call(prompt, runtime):
        return {"content": "   "}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        with pytest.raises(RuntimeError) as exc:
            await generate_playwright_test(
                [{"type": "click", "timestamp": 1}], {}, Mock()
            )
    assert "Failed to generate Playwright test code" in str(exc.value)


@pytest.mark.asyncio
async def test_should_respect_max_screenshots_limit():
    from midscene.core.ai_model.workflows.recorder_generation import (
        generate_playwright_test,
    )

    captured: Dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    events = [{"type": "click", "timestamp": 1}]

    def shots(size, count):
        return [
            {"eventIndex": index, "dataUrl": "data:image/png;base64" + "A" * size}
            for index in range(count)
        ]

    def images_of(prompt):
        return [
            part
            for message in prompt
            if isinstance(message["content"], list)
            for part in message["content"]
            if part["type"] == "image"
        ]

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            events, {"screenshotAssets": shots(1_000, 8)}, Mock()
        )
    # upstream caps the visual context at maxScreenshots (3 by default)
    assert len(images_of(captured["prompt"])) == 3

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            events,
            {"screenshotAssets": shots(250_000, 8), "maxScreenshots": 8},
            Mock(),
        )
    # eight full-size shots would be rejected by the provider outright
    assert (
        sum(len(part["url"]) for part in images_of(captured["prompt"])) <= 600_000
    )

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            events,
            {"screenshotAssets": shots(1_000, 3), "includeScreenshots": False},
            Mock(),
        )
    assert all(isinstance(m["content"], str) for m in captured["prompt"])
