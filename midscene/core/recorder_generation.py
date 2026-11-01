"""Recorder test generation: recorded events -> Midscene YAML test.

Synced from upstream packages/core/src/ai-model/workflows/recorder-generation/
(v1.17.4, yaml.ts + common.ts). The Chrome extension records browser events;
this module converts the event list into an executable Midscene YAML test via
the LLM, preferring AI-generated semantic descriptions when available.
"""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from .ai_model.adapters import ModelRuntime, get_model_runtime
from .ai_model.caller import call_ai_with_string_response

# Upstream YAML_EXAMPLE_CODE is a long reference test file; the generation
# prompt embeds it verbatim. Keep a compact pointer plus the API contract
# section that the model must follow.
YAML_API_CONTRACT = """
IMPORTANT: Follow these exact type signatures for AI functions:
aiAct(prompt: string, options?: { cacheable?: boolean }): Promise<string | undefined>
aiInput(text: string, locate: string, options?: { deepLocate?: boolean, cacheable?: boolean }): Promise<void>
aiTap(locate: string, options?: { deepLocate?: boolean, cacheable?: boolean }): Promise<void>
aiHover(locate: string): Promise<void>
aiDoubleClick(locate: string): Promise<void>
aiKeyboardPress(key: string, locate?: string): Promise<void>
aiScroll(locate: string | undefined, options: { direction?: 'up' | 'down' | 'left' | 'right', scrollType?: 'singleAction' | 'scrollToBottom' | 'scrollToTop' | 'scrollToRight' | 'scrollToLeft', distance?: number | null }): Promise<void>
aiAssert(assertion: string, options?: { errorMessage?: string }): Promise<void>
aiWaitFor(prompt: string, options?: { timeout?: number }): Promise<void>
aiQuery<T>(queryObject: Record<string, string>): Promise<T>
"""


def validate_events(events: List[Dict[str, Any]]) -> None:
    """Recorded events must be non-empty and well-formed (upstream validateEvents)."""
    if not events:
        raise ValueError("no recorded events to convert")
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"event #{index} is not an object")
        if not event.get("type"):
            raise ValueError(f"event #{index} is missing a type")


def create_event_counts(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"navigation": 0, "click": 0, "input": 0, "scroll": 0, "total": len(events)}
    for event in events:
        event_type = event.get("type", "")
        if event_type in counts:
            counts[event_type] += 1
    return counts


def _event_hash_id(event: Dict[str, Any], index: int) -> str:
    raw = json.dumps(event, sort_keys=True, ensure_ascii=False) + str(index)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def process_events_for_llm(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assign hash ids and carry descriptions/values (upstream
    processEventsForLLM)."""
    processed: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        item = dict(event)
        item["hashId"] = _event_hash_id(event, index)
        semantic = event.get("semantic") or {}
        if semantic.get("status") == "ready":
            item["description"] = (
                semantic.get("elementDescription") or event.get("description") or ""
            )
            item["value"] = semantic.get("replayInstruction") or event.get("value") or ""
        processed.append(item)
    return processed


def prepare_event_summary(
    events: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the EventSummary payload embedded in the generation prompt."""
    options = options or {}
    processed = process_events_for_llm(events)
    urls: List[str] = []
    for event in processed:
        url = event.get("url")
        if url and url not in urls:
            urls.append(url)
    return {
        "testName": options.get("testName") or "recorder-test",
        "startUrl": urls[0] if urls else "",
        "eventCounts": create_event_counts(events),
        "urls": urls,
        "clickDescriptions": [
            e.get("description", "") for e in processed if e.get("type") == "click"
        ],
        "inputDescriptions": [
            {"description": e.get("description", ""), "value": e.get("value", "")}
            for e in processed
            if e.get("type") == "input"
        ],
        "events": processed,
    }


def create_default_web_target(
    events: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Default web target from the first navigation event
    (upstream createDefaultWebTarget)."""
    options = options or {}
    navigation = [e for e in events if e.get("type") == "navigation"]
    navigation_info = options.get("navigationInfo") or {}
    first_url = next(
        (u for u in navigation_info.get("urls", []) if u), None
    ) or next((e.get("url") for e in navigation if e.get("url")), "")
    first_viewport = navigation_info.get("initialViewport") or next(
        (e.get("pageInfo") for e in events if e.get("pageInfo")), None
    )
    values: Dict[str, Any] = {"url": first_url}
    if isinstance(first_viewport, dict):
        if first_viewport.get("width"):
            values["viewportWidth"] = first_viewport["width"]
        if first_viewport.get("height"):
            values["viewportHeight"] = first_viewport["height"]
    return {
        "platformId": "web",
        "deviceId": first_url or None,
        "label": first_url or "Web",
        "values": values,
    }


def stringify_target_block(target: Dict[str, Any]) -> str:
    """Serialize the target block for the prompt (upstream
    stringifyMidsceneRecorderTargetBlock)."""
    lines = [f"{target.get('platformId', 'web')}:"]
    for key, value in (target.get("values") or {}).items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _yaml_language_instruction(language: Optional[str]) -> str:
    if not language or not language.strip():
        return ""
    return (
        f"\nLanguage requirement:\n"
        f"- Write all human-readable YAML content in {language.strip()}.\n"
        "- Keep YAML keys, field names, and Midscene API names unchanged."
    )


def create_yaml_prompt(
    yaml_summary: Dict[str, Any],
    target: Dict[str, Any],
    target_block: str,
    screenshot_assets: Optional[List[Dict[str, Any]]] = None,
    language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the generation prompt (upstream createYamlPrompt)."""
    prompt: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert in Midscene.js YAML test generation. "
                "Generate clean, accurate YAML following these rules: "
                + YAML_API_CONTRACT
            ),
        },
        {
            "role": "user",
            "content": f"""Generate YAML test for Midscene.js automation from recorded events.

Target platform:
- Preserve this exact top-level target platform: {target.get('platformId', 'web')}
- Use exactly one top-level target block.
- The target block must be:
{target_block}

Event Summary:
{json.dumps(yaml_summary, ensure_ascii=False, indent=2, default=str)}

Screenshot assets:
{json.dumps([
    {
        "eventIndex": asset.get("eventIndex"),
        "eventHashId": asset.get("eventHashId"),
        "eventType": asset.get("eventType"),
        "relativePath": asset.get("relativePath"),
        "description": (yaml_summary.get("events") or [{}])[asset.get("eventIndex", 0)].get("description"),
    }
    for asset in (screenshot_assets or [])
], ensure_ascii=False, indent=2)}

Convert events:
- navigation → target URL or aiAction only when the target platform supports it
- click → aiTap with the semantic element description
- input → aiInput with value and semantic locate
- scroll → aiScroll with appropriate direction and semantic scroll area
- keydown → aiKeyboardPress
- Add aiAssert for important state changes
- Prefer event.semantic.replayInstruction and event.semantic.elementDescription when event.semantic.source is "aiDescribe" or "recorderAI" and event.semantic.status is "ready".
- If event.semantic.source is "heuristic" or event.semantic.status is "pending"/"failed", use the screenshot/context to write the best visual instruction, and avoid raw coordinates unless there is no reliable semantic description.
- Screenshot assets are context only. Use their eventIndex/eventHashId relationship to understand the matching event, but do not include screenshot file paths in the YAML unless the Midscene YAML API explicitly needs them.{_yaml_language_instruction(language)}

Important: Return ONLY the raw YAML content. Do NOT wrap the response in markdown code blocks (no ```yaml or ```). Start directly with the YAML content.""",
        },
    ]

    if screenshot_assets:
        prompt.append(
            {
                "role": "user",
                "content": "Here are screenshots from the recording session to help you understand the context:",
            }
        )
        prompt.append(
            {
                "role": "user",
                "content": [
                    part
                    for asset in screenshot_assets
                    for part in (
                        {
                            "type": "text",
                            "text": f"Screenshot asset for event #{asset['eventIndex'] + 1}: {asset.get('relativePath', '')}",
                        },
                        {"type": "image", "url": asset.get("dataUrl", "")},
                    )
                ],
            }
        )
    return prompt


def normalize_generated_yaml(content: str) -> str:
    """Strip code fences if the model wrapped the YAML (upstream
    normalizeGeneratedYaml)."""
    trimmed = content.strip()
    fenced = re.match(r"^```(?:ya?ml)?\s*([\s\S]*?)\s*```$", trimmed, re.IGNORECASE)
    return (fenced.group(1) if fenced else trimmed).strip() + "\n"


async def generate_yaml_test(
    events: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    model_runtime: Optional[ModelRuntime] = None,
) -> str:
    """Convert recorded events into a Midscene YAML test
    (upstream generateYamlTest)."""
    try:
        validate_events(events)
        options = dict(options or {})
        target = options.get("target") or create_default_web_target(events, options)
        summary = prepare_event_summary(events, options)
        summary = {
            **summary,
            "target": target,
            "includeTimestamps": bool(options.get("includeTimestamps")),
        }
        target_block = stringify_target_block(target)
        prompt = create_yaml_prompt(
            summary,
            target,
            target_block,
            screenshot_assets=options.get("screenshotAssets"),
            language=options.get("language"),
        )
        runtime = model_runtime or get_model_runtime(
            get_global_default_config()
        )
        response = await call_ai_with_string_response(prompt, runtime)
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Failed to generate recorder YAML test configuration")
        return normalize_generated_yaml(content)
    except Exception as error:
        raise RuntimeError(f"Failed to generate recorder YAML test: {error}") from error


def get_global_default_config() -> Dict[str, Any]:
    from .ai_model.env_config import get_global_model_config_manager

    return get_global_model_config_manager().get_model_config("default")

# ---------------------------------------------------------------------------
# Markdown replay generation (upstream markdown.ts)
# ---------------------------------------------------------------------------

MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET = 600_000
MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE = 768


def limit_screenshot_assets_for_markdown_replay(screenshot_assets):
    """Keep assets within the total payload budget (upstream)."""
    used_payload = 0
    kept = []
    for asset in screenshot_assets:
        payload_size = len(asset.get("dataUrl", ""))
        if (
            payload_size > MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET
            or used_payload + payload_size > MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET
        ):
            continue
        used_payload += payload_size
        kept.append(asset)
    return kept


def prepare_screenshot_assets_for_markdown_replay(screenshot_assets):
    """Shrink assets whose longest edge exceeds 768px, then apply the budget.

    An asset already inside the limit is returned untouched: re-encoding a
    small PNG to JPEG blurs the UI text the model reads and would leave the
    caller's base64Data/mimeType describing a different image (upstream
    compressScreenshotAssetForMarkdownReplay returns early for those).
    """
    import base64 as _b64
    import io as _io

    from PIL import Image

    compressed = []
    for asset in screenshot_assets:
        try:
            data_url = asset.get("dataUrl", "")
            raw = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
            image = Image.open(_io.BytesIO(_b64.b64decode(raw)))
            width, height = image.size
            longest_edge = max(width, height)
            if longest_edge <= MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE:
                compressed.append(asset)
                continue
            scale = MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE / longest_edge
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale)))
            )
            buffer = _io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85)
            encoded = _b64.b64encode(buffer.getvalue()).decode("ascii")
            resized = {**asset, "dataUrl": f"data:image/jpeg;base64,{encoded}"}
            if "base64Data" in asset:
                resized["base64Data"] = encoded
            if "mimeType" in asset:
                resized["mimeType"] = "image/jpeg"
            compressed.append(resized)
        except Exception as error:
            logger.debug(
                "failed to compress screenshot asset; keeping original "
                f"eventHashId={asset.get('eventHashId')} "
                f"eventIndex={asset.get('eventIndex')} error={error}"
            )
            compressed.append(asset)
    return limit_screenshot_assets_for_markdown_replay(compressed)


def normalize_generated_markdown(content: str) -> str:
    trimmed = content.strip()
    fenced = re.match(r"^```(?:md|markdown)?\s*([\s\S]*?)\s*```$", trimmed, re.IGNORECASE)
    return (fenced.group(1) if fenced else trimmed).strip() + "\n"


def create_recorder_markdown_replay_prompt(
    input_payload: Dict[str, Any],
    summary: Dict[str, Any],
    screenshot_assets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the Markdown replay prompt (upstream
    createRecorderMarkdownReplayPromptFromContext)."""
    target = input_payload["target"]
    screenshot_index_by_hash = {
        asset["eventHashId"]: f"screenshot-{index + 1}"
        for index, asset in enumerate(screenshot_assets)
    }
    events = []
    for event in summary.get("events", []):
        ref = screenshot_index_by_hash.get(event.get("hashId"))
        item = {k: v for k, v in event.items() if k != "screenshotPath"}
        if ref:
            item["screenshotRef"] = ref
        events.append(item)

    # upstream labels each shot with the semantic-resolved description, which
    # process_events_for_llm already put on the processed events; a stale asset
    # index must not fail the whole generation.
    described_events = summary.get("events") or []
    screenshot_entries = []
    for index, asset in enumerate(screenshot_assets):
        event_index = asset["eventIndex"]
        description = None
        if isinstance(event_index, int) and 0 <= event_index < len(described_events):
            description = described_events[event_index].get("description")
        screenshot_entries.append(
            {
                "screenshotRef": f"screenshot-{index + 1}",
                "eventIndex": event_index,
                "eventHashId": asset["eventHashId"],
                "eventType": asset.get("eventType"),
                "description": description,
            }
        )

    prompt_payload = {
        "testName": input_payload.get("testName") or summary.get("testName"),
        "target": {
            "platformId": target.get("platformId"),
            "label": target.get("label"),
            "values": target.get("values"),
        },
        "startUrl": summary.get("startUrl"),
        "events": events,
        "screenshots": screenshot_entries,
    }
    test_name = input_payload.get("testName") or summary.get("testName")

    prompt_text = f"""Generate a Markdown replay script for Midscene Agent. It will be executed with:
await agent.aiAct(markdownReplayPrompt)

Use only the recorder data and screenshots below.

Target block:
{stringify_target_block(target)}

Replay goal:
- Reproduce the recorded user workflow exactly.
- Preserve event order.
- Preserve the user's original intent.
- Do not invent alternative navigation paths.
- Do not skip, merge, reorder, or add extra user actions.
- Prefer recorded UI text, element descriptions, URLs, input values, and scroll direction.
- For input events, enter event.typedText/event.value exactly; do not infer or correct the text from screenshots.
- Prefer event.semantic.replayInstruction and event.semantic.elementDescription when event.semantic.source is "aiDescribe" or "recorderAI" and event.semantic.status is "ready".
- For scroll events, preserve the recorded scroll region from event.semantic.elementDescription/replayInstruction. If the scroll happened in a specific panel, list, table, dialog body, menu, navigation area, or content pane, keep that region in the Markdown step instead of generalizing it to the whole page.
- If event.semantic.source is "heuristic" or event.semantic.status is "pending"/"failed", use the screenshot/context to write the best visual instruction.
- Coordinates are only fallback hints. Do not make coordinates the primary instruction when text or screenshots are available.
- For a click/tap that only focuses a field before an input event, describe the target as the field/control itself. Do not target a placeholder character, typed character, caret, or inner text fragment inside the field.
- If a target cannot be found, stop and report the missing step. Do not click similar-looking elements.
- Screenshots are only generation-time visual evidence for you. The generated Markdown will be passed directly to agent.aiAct(markdownReplayPrompt), which accepts text only and cannot receive attached images.
- Convert any useful screenshot evidence into textual replay instructions. Do not include screenshots, image syntax, image paths, or reference-image names in the generated Markdown.
- Never write Markdown image syntax such as ![step context](...), reference-style images, HTML <img> tags, ./screenshots/... paths, or screenshot-* names in the output.

Required structure:
# {test_name}

## Goal
Reproduce the recorded user workflow exactly.

## Target
- Platform: {target.get('platformId')}
- Start target: {summary.get('startUrl') or target.get('label') or target.get('deviceId') or 'Recorded target'}

## Steps
1. ...

Recorder data:
{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)}{_markdown_language_instruction(input_payload.get('language'))}

Important: Return ONLY raw Markdown. Do NOT wrap the response in markdown code blocks."""

    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for asset in screenshot_assets:
        screenshot_ref = screenshot_index_by_hash.get(asset["eventHashId"])
        content.append(
            {
                "type": "text",
                "text": f"{screenshot_ref} for event #{asset['eventIndex'] + 1}",
            }
        )
        content.append({"type": "image", "url": asset.get("dataUrl", "")})

    return [
        {
            "role": "system",
            "content": (
                "You generate precise Markdown replay scripts for Midscene "
                "agent.aiAct. The final output is plain text that will be passed "
                "directly to agent.aiAct, so it must be deterministic, ordered, "
                "safe for AI execution, and must not contain image references, "
                "screenshot paths, or screenshot labels."
            ),
        },
        {"role": "user", "content": content},
    ]


def _markdown_language_instruction(language: Optional[str]) -> str:
    if not language or not language.strip():
        return ""
    nl = chr(10)
    return (
        f"{nl}Language requirement:{nl}"
        f"- Write all human-readable Markdown instructions in {language.strip()}.{nl}"
        "- Keep file paths, URLs, platform ids, API names, and quoted UI text unchanged."
    )


async def generate_markdown_replay(
    events: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    model_runtime: Optional[ModelRuntime] = None,
) -> str:
    """Convert recorded events into a Markdown replay script consumed by
    agent.aiAct (upstream generateRecorderMarkdownReplay)."""
    try:
        validate_events(events)
        options = dict(options or {})
        target = options.get("target") or create_default_web_target(events, options)
        summary = prepare_event_summary(events, options)
        assets = prepare_screenshot_assets_for_markdown_replay(
            options.get("screenshotAssets") or []
        )
        input_payload = {
            "testName": options.get("testName"),
            "target": target,
            "events": events,
            "language": options.get("language"),
        }
        prompt = create_recorder_markdown_replay_prompt(
            input_payload, summary, assets
        )
        runtime = model_runtime or get_model_runtime(get_global_default_config())
        response = await call_ai_with_string_response(prompt, runtime)
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Failed to generate recorder Markdown replay")
        return normalize_generated_markdown(content)
    except Exception as error:
        raise RuntimeError(
            f"Failed to generate recorder Markdown replay: {error}"
        ) from error


# ---------------------------------------------------------------------------
# Playwright test generation (upstream playwright.ts)
# ---------------------------------------------------------------------------

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
    response = await call_ai_with_string_response(prompt, runtime)
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Failed to generate Playwright test code")
    # the prompt already forbids fences; strip them anyway (upstream returns the
    # model output verbatim) so a wrapped reply still saves as runnable code
    fenced = re.match(r"^```(?:typescript|javascript|ts|js)?\s*([\s\S]*?)\s*```$", content.strip(), re.IGNORECASE)
    return (fenced.group(1) if fenced else content).strip() + "\n"
