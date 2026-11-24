"""Recorded events -> Midscene YAML test (upstream recorder-generation/yaml.ts)."""

import json
import re
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
    prepare_recorder_generation_context,
    process_events_for_llm,
    recorder_stream_options,
    resolve_model_runtime,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.common import (
    stringify_target_block as _stringify_target_block,
)
from midscene.shared.constants import YAML_EXAMPLE_CODE


def create_default_web_target(
    events: list[dict[str, Any]], options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Default web target from the first navigation event (upstream)."""
    options = options or {}
    navigation_events = [event for event in events if event.get("type") == "navigation"]
    navigation_info = options.get("navigationInfo") or {}
    first_url = next(
        (url for url in navigation_info.get("urls") or [] if url), None
    ) or next(
        (event.get("url") for event in navigation_events if event.get("url")),
        "",
    )
    first_viewport = navigation_info.get("initialViewport") or next(
        (event.get("pageInfo") for event in events if event.get("pageInfo")), None
    )

    values: dict[str, Any] = {"url": first_url}
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


def get_yaml_language_instruction(language: str | None) -> str:
    normalized = (language or "").strip()
    if not normalized:
        return ""
    return (
        "\nLanguage requirement:\n"
        f"- Write all human-readable YAML content in {normalized}.\n"
        "- Keep YAML keys, field names, and Midscene API names unchanged."
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def create_yaml_prompt(
    yaml_summary: dict[str, Any],
    screenshot_assets: list[dict[str, Any]] | None = None,
    language: str | None = None,
    target_block: str = "",
    target: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the generation prompt (upstream createYamlPrompt)."""
    screenshot_assets = screenshot_assets or []
    target = target or {"platformId": (yaml_summary or {}).get("platformId", "web")}
    events = yaml_summary.get("events") or []

    prompt: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert in Midscene.js YAML test generation. "
                "Generate clean, accurate YAML following these rules: "
                f"{YAML_EXAMPLE_CODE}"
            ),
        },
        {
            "role": "user",
            "content": f"""Generate YAML test for Midscene.js automation from recorded events.

Target platform:
- Preserve this exact top-level target platform: {target.get("platformId", "web")}
- Use exactly one top-level target block.
- The target block must be:
{target_block}

Event Summary:
{_json_dumps(yaml_summary)}

Screenshot assets:
{
                _json_dumps(
                    [
                        {
                            "eventIndex": asset.get("eventIndex"),
                            "eventHashId": asset.get("eventHashId"),
                            "eventType": asset.get("eventType"),
                            "relativePath": asset.get("relativePath"),
                            "description": (
                                events[asset.get("eventIndex", 0)].get("description")
                                if isinstance(asset.get("eventIndex"), int)
                                and 0 <= asset.get("eventIndex", 0) < len(events)
                                else None
                            ),
                        }
                        for asset in screenshot_assets
                    ]
                )
            }

Convert events:
- navigation → target URL or aiAction only when the target platform supports it
- click → aiTap with the semantic element description
- input → aiInput with value and semantic locate
- scroll → aiScroll with appropriate direction and semantic scroll area
- keydown → aiKeyboardPress
- Add aiAssert for important state changes
- Prefer event.semantic.replayInstruction and event.semantic.elementDescription when event.semantic.source is "aiDescribe" or "recorderAI" and event.semantic.status is "ready".
- If event.semantic.source is "heuristic" or event.semantic.status is "pending"/"failed", use the screenshot/context to write the best visual instruction, and avoid raw coordinates unless there is no reliable semantic description.
- Screenshot assets are context only. Use their eventIndex/eventHashId relationship to understand the matching event, but do not include screenshot file paths in the YAML unless the Midscene YAML API explicitly needs them.{
                get_yaml_language_instruction(language)
            }

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
    """Strip code fences if the model wrapped the YAML (upstream)."""
    trimmed = content.strip()
    fenced = re.match(r"^```(?:ya?ml)?\s*([\s\S]*?)\s*```$", trimmed, re.IGNORECASE)
    return (fenced.group(1) if fenced else trimmed).strip() + "\n"


def create_recorder_yaml_prompt(
    input_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    context = prepare_recorder_generation_context(input_payload)
    target = input_payload["target"]
    yaml_summary = {
        **context["summary"],
        "target": target,
        "includeTimestamps": bool(input_payload.get("includeTimestamps")),
    }
    return create_yaml_prompt(
        yaml_summary,
        context["screenshotAssets"],
        input_payload.get("language"),
        _stringify_target_block(target),
        target,
    )


async def generate_recorder_yaml_test(
    input_payload: dict[str, Any], model_config: Any
) -> str:
    try:
        prompt = create_recorder_yaml_prompt(input_payload)
        response = await call_ai_with_string_response(
            prompt, resolve_model_runtime(model_config)
        )
        content = (response or {}).get("content")
        if isinstance(content, str) and content:
            return normalize_generated_yaml(content)
        raise RuntimeError("Failed to generate recorder YAML test configuration")
    except Exception as error:
        raise RuntimeError(f"Failed to generate recorder YAML test: {error}") from error


async def generate_recorder_yaml_test_stream(
    input_payload: dict[str, Any],
    options: dict[str, Any],
    model_config: Any,
) -> dict[str, Any]:
    try:
        prompt = create_recorder_yaml_prompt(input_payload)
        runtime = resolve_model_runtime(model_config)
        stream_options = recorder_stream_options(options)
        if stream_options:
            response = await call_generative_ai(prompt, runtime, stream_options)
            return {**response, "isStreamed": True}

        response = await call_ai_with_string_response(prompt, runtime)
        content = (response or {}).get("content")
        if isinstance(content, str) and content:
            return {
                "content": normalize_generated_yaml(content),
                "usage": (response or {}).get("usage"),
                "isStreamed": False,
            }
        raise RuntimeError("Failed to generate recorder YAML test configuration")
    except Exception as error:
        raise RuntimeError(f"Failed to generate recorder YAML test: {error}") from error


async def generate_yaml_test(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    model_config: Any = None,
) -> str:
    """Generates YAML test configuration from recorded events using AI."""
    options = dict(options or {})
    return await generate_recorder_yaml_test(
        {
            **options,
            "target": create_default_web_target(events, options),
            "events": events,
        },
        model_config,
    )


async def generate_yaml_test_stream(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    model_config: Any = None,
) -> dict[str, Any]:
    """Generates YAML test configuration with streaming support."""
    options = dict(options or {})
    return await generate_recorder_yaml_test_stream(
        {
            **options,
            "target": create_default_web_target(events, options),
            "events": events,
        },
        options,
        model_config,
    )


__all__ = [
    "create_default_web_target",
    "create_event_counts",
    "create_message_content",
    "create_recorder_yaml_prompt",
    "create_yaml_prompt",
    "extract_input_descriptions",
    "filter_events_by_type",
    "generate_recorder_yaml_test",
    "generate_recorder_yaml_test_stream",
    "generate_yaml_test",
    "generate_yaml_test_stream",
    "get_screenshots_for_llm",
    "get_yaml_language_instruction",
    "normalize_generated_yaml",
    "prepare_event_summary",
    "prepare_recorder_generation_context",
    "process_events_for_llm",
    "validate_events",
]
