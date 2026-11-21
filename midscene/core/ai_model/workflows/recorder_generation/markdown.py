"""Markdown replay generation (upstream recorder-generation/markdown.ts)."""

from typing import Any, Dict, List, Optional
import json
import re
from loguru import logger
from midscene.core.ai_model.models.registry import ModelRuntime, get_model_runtime
from midscene.core.ai_model.service_caller.call_ai import call_ai_with_string_response

from midscene.core.ai_model.workflows.recorder_generation.common import (
    get_global_default_config,
    prepare_event_summary,
    stringify_target_block,
    validate_events,
)
from midscene.core.ai_model.workflows.recorder_generation.yaml import (
    create_default_web_target,
)

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
