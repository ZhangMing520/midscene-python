"""Synced from upstream
``packages/core/tests/unit-test/workflows/recorder-generation/playwright.test.ts``."""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from midscene.core.ai_model.workflows.recorder_generation import (
    create_event_counts,
    create_message_content,
    extract_input_descriptions,
    filter_events_by_type,
    generate_playwright_test,
    generate_playwright_test_stream,
    get_screenshots_for_llm,
    prepare_event_summary,
    process_events_for_llm,
    validate_events,
)


def _mock_events() -> list[dict[str, Any]]:
    return [
        {
            "type": "navigation",
            "timestamp": 1000,
            "url": "https://example.com",
            "title": "Example Page",
            "screenshotBefore": "data:image/png;base64,screenshot1",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "nav-1",
        },
        {
            "type": "click",
            "timestamp": 2000,
            "semantic": {
                "source": "heuristic",
                "status": "ready",
                "elementDescription": "Login button",
            },
            "screenshotWithBox": "data:image/png;base64,screenshot2",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "click-1",
        },
        {
            "type": "input",
            "timestamp": 3000,
            "semantic": {
                "source": "heuristic",
                "status": "ready",
                "elementDescription": "Username field",
            },
            "value": "testuser",
            "screenshotAfter": "data:image/png;base64,screenshot3",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "input-1",
        },
        {
            "type": "scroll",
            "timestamp": 4000,
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "scroll-1",
        },
    ]


def test_get_screenshots_for_llm_should_keep_screenshot_context_distributed_across_the_timeline():
    screenshots = get_screenshots_for_llm(_mock_events(), 2)

    assert len(screenshots) == 2
    assert screenshots[0] == "data:image/png;base64,screenshot1"
    assert screenshots[1] == "data:image/png;base64,screenshot3"


def test_get_screenshots_for_llm_should_respect_max_screenshots_limit():
    screenshots = get_screenshots_for_llm(_mock_events(), 1)

    assert len(screenshots) == 1
    assert screenshots[0] == "data:image/png;base64,screenshot1"


def test_get_screenshots_for_llm_should_prefer_screenshot_with_box_over_others():
    events = [
        {
            "type": "click",
            "timestamp": 1000,
            "screenshotBefore": "data:image/png;base64,before",
            "screenshotAfter": "data:image/png;base64,after",
            "screenshotWithBox": "data:image/png;base64,withbox",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "box-click",
        }
    ]

    screenshots = get_screenshots_for_llm(events, 1)
    assert screenshots[0] == "data:image/png;base64,withbox"


def test_filter_events_by_type_should_correctly_categorize_events_by_type():
    filtered = filter_events_by_type(_mock_events())

    assert len(filtered["navigationEvents"]) == 1
    assert len(filtered["clickEvents"]) == 1
    assert len(filtered["inputEvents"]) == 1
    assert len(filtered["scrollEvents"]) == 1
    assert filtered["navigationEvents"][0]["type"] == "navigation"
    assert filtered["clickEvents"][0]["type"] == "click"
    assert filtered["inputEvents"][0]["type"] == "input"
    assert filtered["scrollEvents"][0]["type"] == "scroll"


def test_create_event_counts_should_create_accurate_event_counts():
    events = _mock_events()
    filtered = filter_events_by_type(events)
    counts = create_event_counts(filtered, len(events))

    assert counts == {
        "navigation": 1,
        "click": 1,
        "input": 1,
        "scroll": 1,
        "total": 4,
    }


def test_extract_input_descriptions_should_extract_input_descriptions_with_values():
    input_descriptions = extract_input_descriptions(_mock_events())

    assert len(input_descriptions) == 1
    assert input_descriptions[0] == {
        "description": "Username field",
        "value": "testuser",
    }


def test_extract_input_descriptions_should_filter_out_events_without_description_or_value():
    events = [
        {
            "type": "input",
            "timestamp": 1000,
            "semantic": {
                "source": "heuristic",
                "status": "ready",
                "elementDescription": "",
            },
            "value": "test",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "empty-input",
        },
        {
            "type": "input",
            "timestamp": 2000,
            "semantic": {
                "source": "heuristic",
                "status": "ready",
                "elementDescription": "Field",
            },
            "value": "",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "empty-value",
        },
        {
            "type": "input",
            "timestamp": 3000,
            "semantic": {
                "source": "heuristic",
                "status": "ready",
                "elementDescription": "Valid field",
            },
            "value": "valid value",
            "pageInfo": {"width": 1280, "height": 800},
            "hashId": "valid-input",
        },
    ]

    input_descriptions = extract_input_descriptions(events)
    assert len(input_descriptions) == 1
    assert input_descriptions[0]["description"] == "Valid field"


def test_process_events_for_llm_should_extract_relevant_event_data_for_llm_processing():
    processed = process_events_for_llm(_mock_events())

    assert len(processed) == 4
    first = processed[0]
    assert first["hashId"] == "nav-1"
    assert first["screenshotPath"] is None
    assert first["type"] == "navigation"
    assert first["timestamp"] == 1000
    assert first["url"] == "https://example.com"
    assert first["title"] == "Example Page"
    assert first["semantic"] is None
    assert first["description"] == "Navigate to https://example.com"
    assert first["value"] is None
    assert first["pageInfo"] == {"width": 1280, "height": 800}
    assert first["elementRect"] is None
    assert first["actionType"] is None
    assert first["source"] is None


def test_process_events_for_llm_should_attach_screenshot_paths_when_provided():
    processed = process_events_for_llm(
        _mock_events(),
        {"click-1": "./screenshots/event-002-click.png"},
    )

    assert processed[1]["hashId"] == "click-1"
    assert processed[1]["screenshotPath"] == "./screenshots/event-002-click.png"


def test_prepare_event_summary_should_create_comprehensive_event_summary():
    summary = prepare_event_summary(_mock_events(), {"testName": "Custom Test Name"})

    assert summary["testName"] == "Custom Test Name"
    assert summary["startUrl"] == "https://example.com"
    assert summary["eventCounts"]["total"] == 4
    assert len(summary["events"]) == 4
    assert summary["events"][0]["title"] == "Example Page"
    assert "Login button" in summary["clickDescriptions"]
    assert len(summary["inputDescriptions"]) == 1
    assert "https://example.com" in summary["urls"]


def test_prepare_event_summary_should_use_default_test_name_when_not_provided():
    summary = prepare_event_summary(_mock_events())
    assert summary["testName"] == "Automated test from recorded events"


def test_create_message_content_should_create_message_content_with_text_only():
    content = create_message_content("Test prompt", [], False)

    assert content == [{"type": "text", "text": "Test prompt"}]


def test_create_message_content_should_include_screenshots_when_provided():
    screenshots = ["data:image/png;base64,screenshot1"]
    content = create_message_content("Test prompt", screenshots, True)

    assert len(content) == 3
    assert content[0] == {
        "type": "text",
        "text": "Here are screenshots from the recording session to help you understand the context:",
    }
    assert content[1] == {"type": "text", "text": "Test prompt"}
    assert content[2] == {
        "type": "image",
        "url": "data:image/png;base64,screenshot1",
    }


def test_validate_events_should_not_throw_for_valid_events():
    validate_events(_mock_events())


def test_validate_events_should_throw_for_empty_events_array():
    with pytest.raises(ValueError) as exc:
        validate_events([])
    assert "No events provided for test generation" in str(exc.value)


def _mock_playwright_code() -> str:
    return """import { test as base } from '@playwright/test';
import type { PlayWrightAiFixtureType } from '@midscene/web/playwright';
import { PlaywrightAiFixture } from '@midscene/web/playwright';

const test = base.extend<PlayWrightAiFixtureType>(PlaywrightAiFixture({
  waitForNetworkIdleTimeout: 2000,
}));

test.beforeEach(async ({ page }) => {
  await page.goto('https://example.com');
  await page.setViewportSize({ width: 1280, height: 800 });
});

test('Generated test', async ({ aiInput, aiAssert, aiTap, page }) => {
  await aiAssert('The page shows the login interface');
  await aiInput('testuser', 'in username field');
  await aiTap('click login button');
});"""


@pytest.mark.asyncio
async def test_generate_playwright_test_should_generate_playwright_test_successfully():
    captured: dict[str, Any] = {}
    code = _mock_playwright_code()

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": code, "usage": None}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        result = await generate_playwright_test(_mock_events(), {}, Mock())

    assert result == code
    assert captured["prompt"][0]["role"] == "system"
    assert (
        "You are an expert test automation engineer" in captured["prompt"][0]["content"]
    )
    assert captured["prompt"][1]["role"] == "user"
    assert isinstance(captured["prompt"][1]["content"], list)


@pytest.mark.asyncio
async def test_generate_playwright_test_should_handle_custom_options():
    captured: dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            _mock_events(),
            {
                "testName": "Custom Login Test",
                "viewportSize": {"width": 1920, "height": 1080},
                "waitForNetworkIdle": False,
                "waitForNetworkIdleTimeout": 5000,
                "maxScreenshots": 2,
            },
            Mock(),
        )

    message_content = captured["prompt"][1]["content"]
    prompt_text = next(
        msg["text"] for msg in message_content if "Event Summary:" in msg["text"]
    )
    assert "Custom Login Test" in prompt_text
    assert '"width": 1920' in prompt_text
    assert '"height": 1080' in prompt_text
    assert '"waitForNetworkIdle": false' in prompt_text
    assert '"waitForNetworkIdleTimeout": 5000' in prompt_text


@pytest.mark.asyncio
async def test_generate_playwright_test_should_include_screenshots_when_available():
    captured: dict[str, Any] = {}

    async def fake_call(prompt, runtime):
        captured["prompt"] = prompt
        return {"content": "// test"}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        await generate_playwright_test(
            _mock_events(),
            {"includeScreenshots": True, "maxScreenshots": 2},
            Mock(),
        )

    image_messages = [
        msg for msg in captured["prompt"][1]["content"] if msg["type"] == "image"
    ]
    assert len(image_messages) == 2


@pytest.mark.asyncio
async def test_generate_playwright_test_should_throw_error_for_empty_events():
    with pytest.raises(ValueError) as exc:
        await generate_playwright_test([], {}, Mock())
    assert "No events provided for test generation" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_playwright_test_should_handle_ai_call_failure():
    async def fake_call(prompt, runtime):
        raise RuntimeError("AI service unavailable")

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_ai_with_string_response",
        new=fake_call,
    ):
        with pytest.raises(RuntimeError) as exc:
            await generate_playwright_test(_mock_events(), {}, Mock())
    assert "AI service unavailable" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_playwright_test_stream_uses_streaming_when_requested():
    captured: dict[str, Any] = {}

    async def fake_call(prompt, runtime, options):
        captured["prompt"] = prompt
        captured["options"] = options
        return {"content": "// streamed", "usage": None}

    with patch(
        "midscene.core.ai_model.workflows.recorder_generation.playwright.call_generative_ai",
        new=fake_call,
    ):
        result = await generate_playwright_test_stream(
            _mock_events(),
            {"stream": True, "onChunk": lambda chunk: None},
            Mock(),
        )

    assert result["isStreamed"] is True
    assert captured["options"]["stream"] is True
    text = next(
        msg["text"]
        for msg in captured["prompt"][1]["content"]
        if "Event Summary:" in msg["text"]
    )
    assert "can't wrap this test code in markdown code block" in text
