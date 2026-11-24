"""Markdown replay generation (upstream recorder-generation/markdown.ts)."""

import base64
import io
import json
import re
from typing import Any, cast

from loguru import logger
from PIL import Image

from midscene.core.ai_model.service_caller.call_ai import call_ai_with_string_response
from midscene.core.ai_model.workflows.recorder_generation.common import (
    get_midscene_recorder_event_description,
    prepare_recorder_generation_context,
    resolve_model_runtime,
    stringify_target_block,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.yaml import (
    create_default_web_target,
)

MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET = 600_000

MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE = 768


def limit_screenshot_assets_for_markdown_replay(
    screenshot_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
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


def _decode_data_url(data_url: str) -> tuple[str, str]:
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url)
    if match:
        return match.group(1), match.group(2)
    return "image/png", data_url


def _image_info_of_base64(data_url: str) -> tuple[int, int]:
    _, raw = _decode_data_url(data_url)
    with Image.open(io.BytesIO(base64.b64decode(raw))) as image:
        return cast(tuple[int, int], image.size)


def _compress_screenshot_asset_for_markdown_replay(
    asset: dict[str, Any],
) -> dict[str, Any]:
    width, height = _image_info_of_base64(asset.get("dataUrl", ""))
    longest_edge = max(width, height)
    if longest_edge <= MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE:
        return asset

    _, raw = _decode_data_url(asset.get("dataUrl", ""))
    with Image.open(io.BytesIO(base64.b64decode(raw))) as image:
        scale = MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE / longest_edge
        resized = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale)))
        )
        buffer = io.BytesIO()
        resized.convert("RGB").save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        **asset,
        "dataUrl": f"data:image/jpeg;base64,{encoded}",
        "base64Data": encoded,
        "mimeType": "image/jpeg",
    }


def prepare_screenshot_assets_for_markdown_replay(
    screenshot_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Shrink oversized assets, then apply the payload budget (upstream)."""
    compressed = []
    for asset in screenshot_assets:
        try:
            compressed.append(_compress_screenshot_asset_for_markdown_replay(asset))
        except Exception as error:  # noqa: BLE001 - upstream keeps the original
            logger.debug(
                "failed to compress screenshot asset; keeping original "
                f"eventHashId={asset.get('eventHashId')} "
                f"eventIndex={asset.get('eventIndex')} error={error}"
            )
            compressed.append(asset)
    return limit_screenshot_assets_for_markdown_replay(compressed)


def _summarize_screenshot_assets(
    screenshot_assets: list[dict[str, Any]],
) -> dict[str, int]:
    payload_sizes = [len(asset.get("dataUrl", "")) for asset in screenshot_assets]
    return {
        "count": len(screenshot_assets),
        "totalPayloadChars": sum(payload_sizes),
        "maxPayloadChars": max(payload_sizes) if payload_sizes else 0,
    }


def _get_prompt_shape(prompt: list[dict[str, Any]]) -> dict[str, int]:
    text_chars = 0
    image_count = 0
    for message in prompt:
        content = message.get("content")
        if isinstance(content, str):
            text_chars += len(content)
            continue
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_chars += len(str(part.get("text", "")))
            if isinstance(part, dict) and part.get("type") == "image":
                image_count += 1
    return {"textChars": text_chars, "imageCount": image_count}


def _remove_omitted_screenshot_paths(
    summary: dict[str, Any], screenshot_assets: list[dict[str, Any]]
) -> dict[str, Any]:
    included_paths = {asset.get("relativePath") for asset in screenshot_assets}
    return {
        **summary,
        "events": [
            (
                {**event, "screenshotPath": None}
                if event.get("screenshotPath")
                and event.get("screenshotPath") not in included_paths
                else event
            )
            for event in summary.get("events", [])
        ],
    }


def _markdown_language_instruction(language: str | None) -> str:
    normalized = (language or "").strip()
    if not normalized:
        return ""
    nl = chr(10)
    return (
        f"{nl}Language requirement:{nl}"
        f"- Write all human-readable Markdown instructions in {normalized}.{nl}"
        "- Keep file paths, URLs, platform ids, API names, and quoted UI text unchanged."
    )


def normalize_generated_markdown(content: str) -> str:
    trimmed = content.strip()
    fenced = re.match(
        r"^```(?:md|markdown)?\s*([\s\S]*?)\s*```$", trimmed, re.IGNORECASE
    )
    return (fenced.group(1) if fenced else trimmed).strip() + "\n"


def _create_recorder_markdown_replay_prompt_from_context(
    input_payload: dict[str, Any],
    summary: dict[str, Any],
    screenshot_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target = input_payload["target"]
    screenshot_index_by_hash = {
        asset["eventHashId"]: f"screenshot-{index + 1}"
        for index, asset in enumerate(screenshot_assets)
    }

    events = []
    for event in summary.get("events", []):
        screenshot_ref = screenshot_index_by_hash.get(event.get("hashId"))
        event_without_path = {
            key: value for key, value in event.items() if key != "screenshotPath"
        }
        if screenshot_ref:
            event_without_path["screenshotRef"] = screenshot_ref
        events.append(event_without_path)

    input_events = input_payload.get("events") or []
    screenshots = []
    for index, asset in enumerate(screenshot_assets):
        event_index = asset["eventIndex"]
        description = None
        if isinstance(event_index, int) and 0 <= event_index < len(input_events):
            description = get_midscene_recorder_event_description(
                input_events[event_index]
            )
        screenshots.append(
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
        "screenshots": screenshots,
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
- Platform: {target.get("platformId")}
- Start target: {summary.get("startUrl") or target.get("label") or target.get("deviceId") or "Recorded target"}

## Steps
1. ...

Recorder data:
{json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)}{_markdown_language_instruction(input_payload.get("language"))}

Important: Return ONLY raw Markdown. Do NOT wrap the response in markdown code blocks."""

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
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


def create_recorder_markdown_replay_prompt(
    input_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the Markdown replay prompt (upstream, synchronous variant)."""
    validate_events(input_payload.get("events") or [])
    context = prepare_recorder_generation_context(input_payload)
    screenshot_assets = limit_screenshot_assets_for_markdown_replay(
        context["screenshotAssets"]
    )
    summary = _remove_omitted_screenshot_paths(context["summary"], screenshot_assets)
    return _create_recorder_markdown_replay_prompt_from_context(
        input_payload, summary, screenshot_assets
    )


async def _create_recorder_markdown_replay_prompt_for_generation(
    input_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    validate_events(input_payload.get("events") or [])
    context = prepare_recorder_generation_context(input_payload)
    screenshot_assets = prepare_screenshot_assets_for_markdown_replay(
        context["screenshotAssets"]
    )
    summary = _remove_omitted_screenshot_paths(context["summary"], screenshot_assets)
    prompt = _create_recorder_markdown_replay_prompt_from_context(
        input_payload, summary, screenshot_assets
    )
    logger.debug(
        "markdown replay prompt shape "
        f"eventCount={len(input_payload.get('events') or [])} "
        f"maxScreenshots={input_payload.get('maxScreenshots')} "
        f"rawScreenshots={_summarize_screenshot_assets(context['screenshotAssets'])} "
        f"includedScreenshots={_summarize_screenshot_assets(screenshot_assets)} "
        f"prompt={_get_prompt_shape(prompt)}"
    )
    return prompt


async def generate_recorder_markdown_replay(
    input_payload: dict[str, Any], model_config: Any
) -> str:
    try:
        prompt = await _create_recorder_markdown_replay_prompt_for_generation(
            input_payload
        )
        response = await call_ai_with_string_response(
            prompt, resolve_model_runtime(model_config)
        )
        content = (response or {}).get("content")
        if isinstance(content, str) and content:
            return normalize_generated_markdown(content)
        raise RuntimeError("Failed to generate recorder Markdown replay")
    except Exception as error:
        raise RuntimeError(
            f"Failed to generate recorder Markdown replay: {error}"
        ) from error


async def convert_record_log_into_markdown(
    log: dict[str, Any], model_config: Any
) -> str:
    return await generate_recorder_markdown_replay(log, model_config)


async def generate_markdown_replay(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    model_config: Any = None,
) -> str:
    """Backward-compatible wrapper around ``generate_recorder_markdown_replay``."""
    options = dict(options or {})
    target = options.pop("target", None) or create_default_web_target(events, options)
    return await generate_recorder_markdown_replay(
        {**options, "target": target, "events": events}, model_config
    )


__all__ = [
    "MARKDOWN_REPLAY_SCREENSHOT_MAX_EDGE",
    "MARKDOWN_REPLAY_SCREENSHOT_PAYLOAD_BUDGET",
    "convert_record_log_into_markdown",
    "create_recorder_markdown_replay_prompt",
    "generate_markdown_replay",
    "generate_recorder_markdown_replay",
    "limit_screenshot_assets_for_markdown_replay",
    "normalize_generated_markdown",
    "prepare_screenshot_assets_for_markdown_replay",
]
