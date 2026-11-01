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
