"""Playwright test generation (upstream recorder-generation/playwright.ts)."""

from typing import Any, Dict, List, Optional
import json
import re
from midscene.core.ai_model.models.registry import ModelRuntime, get_model_runtime
from midscene.core.ai_model.service_caller.call_ai import call_ai_with_string_response

from midscene.core.ai_model.workflows.recorder_generation.common import (
    _recorder_stream_options,
    get_global_default_config,
    prepare_event_summary,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.markdown import (
    limit_screenshot_assets_for_markdown_replay,
)

# upstream getScreenshotsForLLM caps the playwright visual context at three
# shots (options.maxScreenshots || 3)
PLAYWRIGHT_MAX_SCREENSHOTS = 3


# upstream createMessageContent announces the attached shots with this line
PLAYWRIGHT_SCREENSHOTS_INTRO = (
    "Here are screenshots from the recording session to help you "
    "understand the context:"
)


# Upstream embeds the whole PLAYWRIGHT_EXAMPLE_CODE reference test. The Python
# SDK keeps what a model cannot guess instead: the exact signatures and the
# fixture wiring every generated file has to reproduce.
PLAYWRIGHT_EXAMPLE_REFERENCE = """
// The following is Playwright syntax with the Midscene AI fixture, for reference
IMPORTANT: Follow these exact type signatures for AI functions:
aiAct(prompt: string, options?: { cacheable?: boolean }): Promise<string | undefined>
aiInput(text: string, locate: string, options?: { deepLocate?: boolean, xpath?: string, cacheable?: boolean }): Promise<void>
aiTap(locate: string, options?: { deepLocate?: boolean, xpath?: string, cacheable?: boolean }): Promise<void>
aiHover(locate: string): Promise<void>
aiDoubleClick(locate: string): Promise<void>
aiKeyboardPress(key: string, locate?: string): Promise<void>
aiScroll(locate: string | undefined, options: { direction?: 'up' | 'down' | 'left' | 'right', scrollType?: 'singleAction' | 'scrollToBottom' | 'scrollToTop' | 'scrollToRight' | 'scrollToLeft', distance?: number | null }): Promise<void>
aiAssert(assertion: string, options?: { errorMessage?: string }): Promise<void>
aiWaitFor(prompt: string, options?: { timeout?: number }): Promise<void>
aiQuery<T>(queryObject: Record<string, string>): Promise<T>

// Reproduce this structure, imports and fixture wiring included:
import { test as base } from '@playwright/test';
import type { PlayWrightAiFixtureType } from '@midscene/web/playwright';
import { PlaywrightAiFixture } from '@midscene/web/playwright';

const test = base.extend<PlayWrightAiFixtureType>(PlaywrightAiFixture({
  waitForNetworkIdleTimeout: 2000,
}));

test.beforeEach(async ({ page }) => {
  await page.goto('<startUrl from the event summary>');
  await page.setViewportSize({ width: 1280, height: 800 });
});

test('<testName>', async ({ aiTap, aiInput, aiAssert, aiQuery, aiKeyboardPress, aiScroll, aiWaitFor, page }) => {
  await aiAssert('The page shows the login interface');
  await aiInput('user_name', 'in user name input');
  await aiKeyboardPress('Enter', 'Login Button');
  await aiWaitFor('The page shows that the loading is complete');
});
"""


async def generate_playwright_test(
    events: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    model_runtime: Optional[ModelRuntime] = None,
) -> str:
    """Convert recorded events into a Playwright test using the Midscene
    fixture (upstream generatePlaywrightTest)."""
    validate_events(events)
    options = dict(options or {})
    summary = prepare_event_summary(
        events, {"testName": options.get("testName")}
    )
    playwright_summary = {
        **summary,
        # upstream normalizes with `!== false` and `|| 2000`: a null coming from
        # a YAML option bag still means "wait for network idle for two seconds"
        "waitForNetworkIdle": options.get("waitForNetworkIdle") is not False,
        "waitForNetworkIdleTimeout": options.get("waitForNetworkIdleTimeout") or 2000,
        "viewportSize": options.get("viewportSize") or {"width": 1280, "height": 800},
    }

    prompt_text = f"""Generate a Playwright test using @midscene/web/playwright that reproduces this recorded browser session. The test should be based on the following events and follow the structure of the example provided. Make the test descriptive with appropriate assertions and validations.

Event Summary:
{json.dumps(playwright_summary, ensure_ascii=False, indent=2, default=str)}

{PLAYWRIGHT_EXAMPLE_REFERENCE}

Generated code should:
1. Import required dependencies
2. Set up the test with proper configuration
3. Include a beforeEach hook to navigate to the starting URL
4. Implement a test that uses Midscene AI methods (aiTap, aiInput, aiAssert, etc.)
5. Include appropriate assertions and validations
6. Follow best practices for Playwright tests
7. Be ready to execute without further modification

Important: Return ONLY the raw Playwright test code. Do NOT wrap the response in markdown code blocks (no ```typescript, ```javascript or ```). Start directly with the code content."""

    screenshots = []
    if options.get("includeScreenshots", True):
        # upstream caps the shots at maxScreenshots; a whole recording of full
        # PNGs gets the request rejected by the provider instead
        max_screenshots = options.get("maxScreenshots") or PLAYWRIGHT_MAX_SCREENSHOTS
        screenshots = limit_screenshot_assets_for_markdown_replay(
            (options.get("screenshotAssets") or [])[:max_screenshots]
        )

    user_content: Any = prompt_text
    if screenshots:
        # one user message, intro first, then the prompt, then the shots
        # (upstream createMessageContent)
        user_content = [
            {"type": "text", "text": PLAYWRIGHT_SCREENSHOTS_INTRO},
            {"type": "text", "text": prompt_text},
        ]
        for asset in screenshots:
            user_content.append(
                {"type": "text", "text": f"Screenshot for event #{asset['eventIndex'] + 1}"}
            )
            user_content.append({"type": "image", "url": asset.get("dataUrl", "")})

    prompt: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert Playwright test generator specializing in "
                "Midscene AI-powered tests. Generate complete, runnable test code."
            ),
        },
        {"role": "user", "content": user_content},
    ]

    runtime = model_runtime or get_model_runtime(get_global_default_config())
    stream_options = _recorder_stream_options(options)
    if stream_options:
        response = await call_ai_with_string_response(prompt, runtime, stream_options)
    else:
        response = await call_ai_with_string_response(prompt, runtime)
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Failed to generate Playwright test code")
    # the prompt already forbids fences; strip them anyway (upstream returns the
    # model output verbatim) so a wrapped reply still saves as runnable code
    fenced = re.match(r"^```(?:typescript|javascript|ts|js)?\s*([\s\S]*?)\s*```$", content.strip(), re.IGNORECASE)
    return (fenced.group(1) if fenced else content).strip() + "\n"
