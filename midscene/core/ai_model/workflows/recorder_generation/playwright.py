"""Playwright test generation (upstream recorder-generation/playwright.ts)."""

import json
from typing import Any

from midscene.core.ai_model.service_caller.call_ai import (
    call_ai_with_string_response,
    call_generative_ai,
)
from midscene.core.ai_model.workflows.recorder_generation.common import (
    create_event_counts,
    create_message_content,
    extract_input_descriptions,
    filter_events_by_type,
    get_screenshots_for_llm,
    prepare_event_summary,
    process_events_for_llm,
    recorder_stream_options,
    resolve_model_runtime,
    validate_events,
)
from midscene.shared.constants import PLAYWRIGHT_EXAMPLE_CODE

PLAYWRIGHT_SYSTEM_PROMPT = (
    "You are an expert test automation engineer specializing in Playwright and Midscene. \n"
    "Your task is to generate a complete, executable Playwright test using "
    "@midscene/web/playwright that reproduces a recorded browser session.\n\n"
    f"{PLAYWRIGHT_EXAMPLE_CODE}"
)


def _create_playwright_prompt(
    events: list[dict[str, Any]],
    options: dict[str, Any],
    streaming: bool,
) -> list[dict[str, Any]]:
    summary = prepare_event_summary(
        events,
        {
            "testName": options.get("testName"),
            "maxScreenshots": options.get("maxScreenshots") or 3,
        },
    )
    playwright_summary = {
        **summary,
        "waitForNetworkIdle": options.get("waitForNetworkIdle") is not False,
        "waitForNetworkIdleTimeout": options.get("waitForNetworkIdleTimeout") or 2000,
        "viewportSize": options.get("viewportSize") or {"width": 1280, "height": 800},
    }

    screenshots = get_screenshots_for_llm(events, options.get("maxScreenshots") or 3)

    extra_requirement = (
        "\n8. can't wrap this test code in markdown code block" if streaming else ""
    )
    prompt_text = f"""Generate a Playwright test using @midscene/web/playwright that reproduces this recorded browser session. The test should be based on the following events and follow the structure of the example provided. Make the test descriptive with appropriate assertions and validations.

Event Summary:
{json.dumps(playwright_summary, ensure_ascii=False, indent=2, default=str)}

Generated code should:
1. Import required dependencies
2. Set up the test with proper configuration
3. Include a beforeEach hook to navigate to the starting URL
4. Implement a test that uses Midscene AI methods (aiTap, aiInput, aiAssert, etc.)
5. Include appropriate assertions and validations
6. Follow best practices for Playwright tests
7. Be ready to execute without further modification{extra_requirement}

Important: Return ONLY the raw Playwright test code. Do NOT wrap the response in markdown code blocks (no ```typescript, ```javascript or ```). Start directly with the code content."""

    message_content = create_message_content(
        prompt_text,
        screenshots,
        options.get("includeScreenshots") is not False,
    )

    return [
        {"role": "system", "content": PLAYWRIGHT_SYSTEM_PROMPT},
        {"role": "user", "content": message_content},
    ]


async def generate_playwright_test(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    model_config: Any = None,
) -> str:
    """Generates Playwright test code from recorded events (upstream)."""
    options = dict(options or {})
    validate_events(events)
    prompt = _create_playwright_prompt(events, options, streaming=False)
    response = await call_ai_with_string_response(
        prompt, resolve_model_runtime(model_config)
    )
    content = (response or {}).get("content")
    if isinstance(content, str) and content:
        return content
    raise RuntimeError("Failed to generate Playwright test code")


async def generate_playwright_test_stream(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    model_config: Any = None,
) -> dict[str, Any]:
    """Generates Playwright test code with streaming support (upstream)."""
    options = dict(options or {})
    validate_events(events)
    prompt = _create_playwright_prompt(events, options, streaming=True)
    runtime = resolve_model_runtime(model_config)

    stream_options = recorder_stream_options(options)
    if stream_options:
        response = await call_generative_ai(prompt, runtime, stream_options)
        return {**response, "isStreamed": True}

    response = await call_ai_with_string_response(prompt, runtime)
    content = (response or {}).get("content")
    if isinstance(content, str) and content:
        return {
            "content": content,
            "usage": (response or {}).get("usage"),
            "isStreamed": False,
        }
    raise RuntimeError("Failed to generate Playwright test code")


__all__ = [
    "create_event_counts",
    "create_message_content",
    "extract_input_descriptions",
    "filter_events_by_type",
    "generate_playwright_test",
    "generate_playwright_test_stream",
    "get_screenshots_for_llm",
    "prepare_event_summary",
    "process_events_for_llm",
    "validate_events",
]
