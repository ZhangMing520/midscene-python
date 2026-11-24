"""Recorder event helpers (upstream workflows/recorder-generation/common.ts).

Kept in sync with upstream so YAML, Playwright and Markdown generation all
share one event-processing pipeline.
"""

import json
import math
import re
from typing import Any, cast

DEFAULT_MIDSCENE_RECORDER_MARKDOWN_MAX_SCREENSHOTS = 20

MAX_RECORDER_GENERATION_SEMANTIC_TEXT_LENGTH = 1200
MAX_RECORDER_GENERATION_SEMANTIC_ERROR_LENGTH = 400

_AI_ANALYZING_PLACEHOLDER = "AI is analyzing element..."

_DATA_URL_PATTERN = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$")
_BASE64_ONLY_PATTERN = re.compile(r"^[a-zA-Z0-9+/=\s]+$")


# ---------------------------------------------------------------------------
# Event validation / semantic compaction
# ---------------------------------------------------------------------------


def validate_events(events: list[dict[str, Any]]) -> None:
    """Upstream validateEvents only rejects an empty recording."""
    if not events:
        raise ValueError("No events provided for test generation")


def get_midscene_recorder_semantic(
    event: dict[str, Any],
) -> dict[str, Any] | None:
    return event.get("semantic")


def _is_pending_description(value: str | None) -> bool:
    return isinstance(value, str) and value.strip() == _AI_ANALYZING_PLACEHOLDER


def _clean_recorder_semantic_field(value: str | None) -> str | None:
    return None if _is_pending_description(value) else value


def _truncate_recorder_generation_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}... [truncated {len(value) - max_length} chars]"


def _compact_semantic_text(value: str | None) -> str | None:
    cleaned = _clean_recorder_semantic_field(value)
    return (
        _truncate_recorder_generation_text(
            cleaned, MAX_RECORDER_GENERATION_SEMANTIC_TEXT_LENGTH
        )
        if cleaned
        else None
    )


def _compact_semantic_error(value: str | None) -> str | None:
    return (
        _truncate_recorder_generation_text(
            value, MAX_RECORDER_GENERATION_SEMANTIC_ERROR_LENGTH
        )
        if value
        else None
    )


def compact_recorder_semantic_for_generation(
    semantic: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compact semantic text and drop fallback audit chains (upstream)."""
    if not semantic:
        return None

    compacted: dict[str, Any] = {
        "source": semantic.get("source"),
        "status": semantic.get("status"),
        "confidence": semantic.get("confidence"),
        "elementDescription": _compact_semantic_text(
            semantic.get("elementDescription")
        ),
        "replayInstruction": _compact_semantic_text(semantic.get("replayInstruction")),
        "actionSummary": _compact_semantic_text(semantic.get("actionSummary")),
        "error": _compact_semantic_error(semantic.get("error")),
    }
    ai_describe = semantic.get("aiDescribe")
    if ai_describe:
        compacted["aiDescribe"] = {
            "verifyPrompt": ai_describe.get("verifyPrompt"),
            "verifyPassed": ai_describe.get("verifyPassed"),
            "deepLocate": ai_describe.get("deepLocate"),
            "centerDistance": ai_describe.get("centerDistance"),
            "expectedCenter": ai_describe.get("expectedCenter"),
            "actualCenter": ai_describe.get("actualCenter"),
        }
    return compacted


# ---------------------------------------------------------------------------
# Event description / targeting
# ---------------------------------------------------------------------------


def _pointer_action_verb(action_type: str | None) -> str:
    return {
        "Tap": "Tap",
        "DoubleClick": "Double click",
        "LongPress": "Long press",
        "RightClick": "Right click",
    }.get(action_type or "", "Click")


def _drag_action_verb(action_type: str | None) -> str:
    return "Swipe" if action_type == "Swipe" else "Drag"


def get_midscene_recorder_event_description(event: dict[str, Any]) -> str:
    semantic = get_midscene_recorder_semantic(event) or {}

    for field in ("actionSummary", "elementDescription", "replayInstruction"):
        value = semantic.get(field)
        if value and not _is_pending_description(value):
            return cast(str, value)

    if event.get("type") == "navigation" and event.get("url"):
        return f"Navigate to {event['url']}"
    if event.get("value"):
        action_type = event.get("actionType")
        return f"{action_type} {event['value']}" if action_type else event["value"]

    element_rect = event.get("elementRect") or {}
    if element_rect.get("x") is not None and element_rect.get("y") is not None:
        prefix = event.get("actionType") or event.get("type")
        x = int(math.floor(float(element_rect["x"]) + 0.5))
        y = int(math.floor(float(element_rect["y"]) + 0.5))
        return f"{prefix} ({x}, {y})"

    return event.get("actionType") or event.get("type") or ""


def stringify_target_block(target: dict[str, Any]) -> str:
    """Serialize the target block exactly like upstream (JSON scalar quoting)."""
    lines = [f"{target.get('platformId')}:"]
    values = target.get("values") or {}
    if not values:
        lines.append("  {}")
        return "\n".join(lines)
    for key, value in values.items():
        lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Screenshot assets
# ---------------------------------------------------------------------------


def _normalize_markdown_asset_base_dir(base_dir: str | None) -> str:
    value = (base_dir or "./screenshots").rstrip("/")
    if value.startswith("./") or value.startswith("../"):
        return value
    return f"./{value}"


def _pad_event_index(index: int) -> str:
    return str(index + 1).zfill(3)


def _parse_screenshot_data_url(value: str) -> dict[str, str] | None:
    data_url_match = _DATA_URL_PATTERN.match(value)
    if data_url_match:
        mime_type = data_url_match.group(1)
        if "jpeg" in mime_type:
            extension = "jpg"
        else:
            extension = (
                re.sub(r"[^a-zA-Z0-9]", "", mime_type.split("/")[1] or "") or "png"
            )
        return {
            "dataUrl": value,
            "base64Data": data_url_match.group(2),
            "mimeType": mime_type,
            "extension": extension,
        }

    if _BASE64_ONLY_PATTERN.match(value) and value.strip():
        base64_data = re.sub(r"\s+", "", value)
        return {
            "dataUrl": f"data:image/png;base64,{base64_data}",
            "base64Data": base64_data,
            "mimeType": "image/png",
            "extension": "png",
        }

    return None


def _get_recorder_event_screenshot(event: dict[str, Any]) -> str | None:
    return (
        event.get("screenshotWithBox")
        or event.get("screenshotAfter")
        or event.get("screenshotBefore")
    )


def _has_coordinate_fallback(event: dict[str, Any]) -> bool:
    semantic = get_midscene_recorder_semantic(event) or {}
    element_rect = event.get("elementRect") or {}
    return (
        not semantic.get("elementDescription")
        and element_rect.get("x") is not None
        and element_rect.get("y") is not None
    )


def _should_include_markdown_screenshot(
    event: dict[str, Any], event_index: int, last_event_index: int
) -> bool:
    semantic = get_midscene_recorder_semantic(event) or {}
    return (
        event_index == 0
        or event_index == last_event_index
        or event.get("type") in ("navigation", "scroll", "input")
        or bool(event.get("screenshotWithBox"))
        or not semantic.get("elementDescription")
        or _has_coordinate_fallback(event)
    )


def _get_recorder_screenshot_candidates(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_screenshots = set()
    last_event_index = len(events) - 1

    for event_index, event in enumerate(events):
        if not _should_include_markdown_screenshot(
            event, event_index, last_event_index
        ):
            continue
        screenshot = _get_recorder_event_screenshot(event)
        if not screenshot or screenshot in seen_screenshots:
            continue
        seen_screenshots.add(screenshot)
        candidates.append(
            {"event": event, "eventIndex": event_index, "screenshot": screenshot}
        )
    return candidates


def _candidate_priority(
    candidate: dict[str, Any], first_event_index: int, last_event_index: int
) -> int:
    event = candidate["event"]
    priority = 0
    if candidate["eventIndex"] == first_event_index:
        priority += 100
    if candidate["eventIndex"] == last_event_index:
        priority += 95
    if event.get("type") == "navigation":
        priority += 80
    if event.get("screenshotWithBox"):
        priority += 70
    semantic = get_midscene_recorder_semantic(event) or {}
    if (
        semantic.get("source") == "heuristic"
        or semantic.get("confidence") == "low"
        or semantic.get("error")
    ):
        priority += 60
    if event.get("type") in ("input", "scroll"):
        priority += 40
    if not semantic.get("elementDescription") or _has_coordinate_fallback(event):
        priority += 30
    return priority


def _select_evenly_distributed(
    candidates: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    if len(candidates) <= count:
        return candidates
    if count == 1:
        return [candidates[(len(candidates) - 1) // 2]]
    return [
        candidates[int(math.floor((index * (len(candidates) - 1)) / (count - 1) + 0.5))]
        for index in range(count)
    ]


def _select_recorder_screenshot_candidates(
    candidates: list[dict[str, Any]], max_screenshots: int
) -> list[dict[str, Any]]:
    if max_screenshots <= 0 or not candidates:
        return []
    if len(candidates) <= max_screenshots:
        return candidates

    selected: dict[int, dict[str, Any]] = {}
    first_event_index = candidates[0]["eventIndex"]
    last_event_index = candidates[-1]["eventIndex"]

    def add_candidate(candidate: dict[str, Any] | None) -> None:
        if candidate is None or len(selected) >= max_screenshots:
            return
        selected.setdefault(candidate["eventIndex"], candidate)

    def add_evenly(pool: list[dict[str, Any]]) -> None:
        remaining = max_screenshots - len(selected)
        if remaining <= 0:
            return
        unselected = [
            candidate for candidate in pool if candidate["eventIndex"] not in selected
        ]
        for candidate in _select_evenly_distributed(unselected, remaining):
            add_candidate(candidate)

    add_candidate(candidates[0])
    add_candidate(candidates[-1])

    add_evenly(
        [
            candidate
            for candidate in candidates
            if _candidate_priority(candidate, first_event_index, last_event_index) >= 60
        ]
    )
    add_evenly(
        [
            candidate
            for candidate in candidates
            if _candidate_priority(candidate, first_event_index, last_event_index) >= 40
        ]
    )
    add_evenly(candidates)

    return sorted(selected.values(), key=lambda item: item["eventIndex"])


def create_midscene_recorder_markdown_screenshot_assets(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    options = options or {}
    base_dir = _normalize_markdown_asset_base_dir(options.get("baseDir"))
    max_screenshots = options.get(
        "maxScreenshots", DEFAULT_MIDSCENE_RECORDER_MARKDOWN_MAX_SCREENSHOTS
    )
    if max_screenshots is None:
        max_screenshots = DEFAULT_MIDSCENE_RECORDER_MARKDOWN_MAX_SCREENSHOTS

    candidates = []
    for candidate in _get_recorder_screenshot_candidates(events):
        parsed = _parse_screenshot_data_url(candidate["screenshot"])
        if parsed:
            candidates.append({**candidate, "parsedScreenshot": parsed})

    assets = []
    for candidate in _select_recorder_screenshot_candidates(
        candidates, max_screenshots
    ):
        event = candidate["event"]
        parsed = candidate["parsedScreenshot"]
        safe_type = re.sub(r"[^a-zA-Z0-9-]", "-", event.get("type") or "")
        file_name = (
            f"event-{_pad_event_index(candidate['eventIndex'])}-"
            f"{safe_type}.{parsed['extension']}"
        )
        assets.append(
            {
                "eventIndex": candidate["eventIndex"],
                "eventHashId": event.get("hashId"),
                "eventType": event.get("type"),
                "relativePath": f"{base_dir}/{file_name}",
                "dataUrl": parsed["dataUrl"],
                "base64Data": parsed["base64Data"],
                "mimeType": parsed["mimeType"],
            }
        )
    return assets


def get_screenshots_for_llm(
    events: list[dict[str, Any]], max_screenshots: int = 1
) -> list[str]:
    return [
        asset["dataUrl"]
        for asset in create_midscene_recorder_markdown_screenshot_assets(
            events, {"baseDir": "./screenshots", "maxScreenshots": max_screenshots}
        )
    ]


# ---------------------------------------------------------------------------
# Event filtering / summary
# ---------------------------------------------------------------------------


def filter_events_by_type(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "navigationEvents": [
            event for event in events if event.get("type") == "navigation"
        ],
        "clickEvents": [event for event in events if event.get("type") == "click"],
        "inputEvents": [event for event in events if event.get("type") == "input"],
        "scrollEvents": [event for event in events if event.get("type") == "scroll"],
    }


def create_event_counts(
    filtered_events: dict[str, list[dict[str, Any]]], total_events: int
) -> dict[str, int]:
    return {
        "navigation": len(filtered_events["navigationEvents"]),
        "click": len(filtered_events["clickEvents"]),
        "input": len(filtered_events["inputEvents"]),
        "scroll": len(filtered_events["scrollEvents"]),
        "total": total_events,
    }


def extract_input_descriptions(
    input_events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    descriptions = []
    for event in input_events:
        semantic = get_midscene_recorder_semantic(event) or {}
        description = (
            _clean_recorder_semantic_field(semantic.get("elementDescription")) or ""
        )
        value = event.get("value") or ""
        descriptions.append({"description": description, "value": value})
    return [item for item in descriptions if item["description"] and item["value"]]


def process_events_for_llm(
    events: list[dict[str, Any]],
    screenshot_path_by_event_hash: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    screenshot_path_by_event_hash = screenshot_path_by_event_hash or {}
    input_index = 0
    processed: list[dict[str, Any]] = []

    for index, event in enumerate(events):
        previous_event = events[index - 1] if index > 0 else None
        next_event = events[index + 1] if index + 1 < len(events) else None

        previous_input = next(
            (
                candidate
                for candidate in reversed(events[:index])
                if candidate.get("type") == "input"
            ),
            None,
        )
        next_input = next(
            (
                candidate
                for candidate in events[index + 1 :]
                if candidate.get("type") == "input"
            ),
            None,
        )

        is_input = event.get("type") == "input"
        input_sequence_index = None
        if is_input:
            input_index += 1
            input_sequence_index = input_index

        has_neighbor_input = bool(previous_input or next_input)
        neighbor_input_values = None
        if is_input:
            neighbor_input_values = [
                value
                for value in (
                    (previous_input or {}).get("value"),
                    (next_input or {}).get("value"),
                )
                if value
            ] or None

        item: dict[str, Any] = {
            "hashId": event.get("hashId"),
            "type": event.get("type"),
            "timestamp": event.get("timestamp"),
            "source": event.get("source"),
            "actionType": event.get("actionType"),
            "url": event.get("url"),
            "title": event.get("title"),
            "semantic": compact_recorder_semantic_for_generation(
                get_midscene_recorder_semantic(event)
            ),
            "description": get_midscene_recorder_event_description(event),
            "value": event.get("value"),
            "previousActionDescription": (
                get_midscene_recorder_event_description(previous_event)
                if previous_event
                else None
            ),
            "nextActionDescription": (
                get_midscene_recorder_event_description(next_event)
                if next_event
                else None
            ),
            "pageInfo": event.get("pageInfo"),
            "elementRect": event.get("elementRect"),
            "screenshotPath": screenshot_path_by_event_hash.get(
                cast(str, event.get("hashId"))
            ),
        }

        if is_input:
            item.update(
                {
                    "typedText": event.get("value") or "",
                    "inputIndex": input_sequence_index,
                    "isSequentialInput": bool(
                        (previous_event or {}).get("type") == "input"
                        or (next_event or {}).get("type") == "input"
                    ),
                    "hasNeighborInput": has_neighbor_input,
                    "previousInputDescription": (
                        get_midscene_recorder_event_description(previous_input)
                        if previous_input
                        else None
                    ),
                    "neighborInputValues": (
                        neighbor_input_values if neighbor_input_values else None
                    ),
                }
            )

        processed.append(item)
    return processed


def prepare_event_summary(
    events: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    filtered_events = filter_events_by_type(events)
    event_counts = create_event_counts(filtered_events, len(events))

    navigation_events = filtered_events["navigationEvents"]
    start_url = (navigation_events[0].get("url") or "") if navigation_events else ""

    click_descriptions = [
        semantic.get("elementDescription")
        for semantic in (
            get_midscene_recorder_semantic(event) or {}
            for event in filtered_events["clickEvents"]
        )
        if semantic.get("elementDescription")
    ][:10]

    input_descriptions = extract_input_descriptions(filtered_events["inputEvents"])[:10]

    urls = [event.get("url") for event in navigation_events if event.get("url")][:5]

    return {
        "testName": options.get("testName") or "Automated test from recorded events",
        "startUrl": start_url,
        "eventCounts": event_counts,
        "urls": urls,
        "clickDescriptions": click_descriptions,
        "inputDescriptions": input_descriptions,
        "events": process_events_for_llm(
            events, options.get("screenshotPathByEventHash")
        ),
    }


def prepare_recorder_generation_context(
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    events = input_payload.get("events") or []
    validate_events(events)

    max_screenshots = input_payload.get("maxScreenshots")
    if max_screenshots is None:
        max_screenshots = DEFAULT_MIDSCENE_RECORDER_MARKDOWN_MAX_SCREENSHOTS
    screenshot_assets = create_midscene_recorder_markdown_screenshot_assets(
        events, {"baseDir": "./screenshots", "maxScreenshots": max_screenshots}
    )
    screenshot_path_by_event_hash = {
        asset["eventHashId"]: asset["relativePath"] for asset in screenshot_assets
    }

    return {
        "summary": prepare_event_summary(
            events,
            {
                "testName": input_payload.get("testName"),
                "screenshotPathByEventHash": screenshot_path_by_event_hash,
            },
        ),
        "screenshotAssets": screenshot_assets,
    }


def create_message_content(
    prompt_text: str,
    screenshots: list[str] | None = None,
    include_screenshots: bool = True,
) -> list[dict[str, Any]]:
    screenshots = screenshots or []
    message_content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]

    if include_screenshots and screenshots:
        message_content.insert(
            0,
            {
                "type": "text",
                "text": (
                    "Here are screenshots from the recording session to help "
                    "you understand the context:"
                ),
            },
        )
        for screenshot in screenshots:
            message_content.append({"type": "image", "url": screenshot})

    return message_content


# ---------------------------------------------------------------------------
# Model runtime helpers
# ---------------------------------------------------------------------------


def get_global_default_config() -> dict[str, Any]:
    from midscene.shared.env import get_global_model_config_manager

    return get_global_model_config_manager().get_model_config("default")


def resolve_model_runtime(model_config: Any) -> Any:
    """Accept a ModelRuntime, a raw config dict, or a test double."""
    from midscene.core.ai_model.models.registry import ModelRuntime, get_model_runtime

    if isinstance(model_config, ModelRuntime):
        return model_config
    if isinstance(model_config, dict):
        return get_model_runtime(model_config or get_global_default_config())
    return model_config


def recorder_stream_options(
    options: dict[str, Any],
) -> dict[str, Any] | None:
    """Upstream streams only when both `stream` and `onChunk` are provided."""
    if options.get("stream") and options.get("onChunk"):
        return {"stream": True, "onChunk": options["onChunk"]}
    return None


# Backward-compatible private alias used by the other recorder modules.
_recorder_stream_options = recorder_stream_options


__all__ = [
    "DEFAULT_MIDSCENE_RECORDER_MARKDOWN_MAX_SCREENSHOTS",
    "compact_recorder_semantic_for_generation",
    "create_event_counts",
    "create_message_content",
    "create_midscene_recorder_markdown_screenshot_assets",
    "extract_input_descriptions",
    "filter_events_by_type",
    "get_global_default_config",
    "get_midscene_recorder_event_description",
    "get_midscene_recorder_semantic",
    "get_screenshots_for_llm",
    "prepare_event_summary",
    "prepare_recorder_generation_context",
    "process_events_for_llm",
    "recorder_stream_options",
    "resolve_model_runtime",
    "stringify_target_block",
    "validate_events",
]
